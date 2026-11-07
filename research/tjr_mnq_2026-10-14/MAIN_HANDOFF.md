Prepared for Sideri and the ChatGPT session implementing his bot. Research date: October 14, 2026. Sideri confirmed the intended educator is TJR, the creator behind @TJRTrades, and that the existing bot currently connects to prediction markets. Last research revision: 2026-10-14 14:26:18 UTC.

The useful implementation target is a **versioned reconstruction of documented public rules**, with measured agreement against observable TJR decisions. Exact replication and equivalent profits are not established. This Page remains the source specification; the separately linked experimental MNQ prototype supplies runnable offline code. Neither is a validated profitable system or a live trading deployment.

The catalogue contains **43 distinct video IDs**, with **27 publication dates corroborated by indexed primary YouTube metadata**. Coverage includes ten substantial coherent original Boot Camp transcript texts, three January 2026 component-lesson transcripts, and additional transcript sections, summaries and metadata. **Zero videos were audiovisually reviewed.** The October 2 candidate now has a secondary summary with an internal contradiction; original speech for all three October candidates remains unavailable. Complete channel and X inventories were not recovered.

# Experimental implementation

The [MNQ research prototype and validation](https://chatgpt.com/space/page_33c0bb7e8dac81919e012fc502bae98a) contains the complete offline engine and synthetic tests. It freezes one BC23-inspired experiment on the actual December 2025 MNQ contract, with development dates September 22–October 31 and an analyst-unseen holdout November 3–December 12, 2025. Its added definitions are explicit research hypotheses, separate from the June model below.

**65 of 65 synthetic checks passed after independent review and correction of three implementation defects. Historical trades tested: zero. Live paper trading: not started.** Missing inputs are a verified historical dataset, actual account costs, an authoritative session calendar, the bot repository, and a licensed live feed/runtime. The companion records access attempts and paper requirements. Copy its code and tests into the receiving session alongside this source handoff.

# Market and implementation decision

Start with offline reconstruction on the actual chart instruments shown in the selected source version, then a paper or observation adapter. The analysis chart and execution product must be separate fields. Earlier teaching describes index CFD execution; references to S&P and Nasdaq do not by themselves establish the exact exchange contract, broker or feed.

A binary prediction-market order cannot be treated as an equivalent implementation of an index-price entry, stop and target. A standard Kalshi event contract has specified resolution rules and settles to a fixed binary payoff. An index signal translated into an event contract therefore becomes a separate strategy with a specified horizon, strike, resolution source, price and costs. [Kalshi contract explanation](https://news.kalshi.com/p/what-are-event-contracts)

A futures research adapter is a practical candidate for exchange-traded index data and paper execution, conditional on instrument verification. CME lists MES at $5 per index point with a 0.25-point tick worth $1.25, and MNQ at $2 per point with a 0.25-point tick worth $0.50. These are contract mechanics, not a sizing recommendation. Micro contracts have different execution conditions from their larger counterparts; do not assume identical fills. [CME fact card](https://www.cmegroup.com/trading/equity-index/files/cme-micro-e-mini-futures-fact-card.pdf)

Tradovate documents simulation and market-data services, making it one platform to evaluate. Account eligibility, API access, automation permissions, data licensing, fees and suitability for this bot are unverified. No broker was selected or connected. [Tradovate API overview](https://partner.tradovate.com/overview/welcome/introduction-to-tradovate-partner-api)

Implementation scope is offline or observation-only. Preserve the existing prediction-market adapter and its records; do not silently route reconstructed signals into it.

# June 2026 candidate rules

Primary source: [My UPDATED Day Trading Strategy 2026](https://www.youtube.com/watch?v=8PYgFVB0GHE), published June 5, 2026. The available [secondary transcript](https://sozai.app/transcript/updated-day-trading-strategy-2026/) contains duplicated or reordered early passages and conflicting numerical text. The following is provisional extraction, not chart-verified implementation. Approximate locators must be checked against the original.

| Rule | Extracted teaching | Approximate locator |
| --- | --- | --- |
| E26 01 | Seek a breach of relevant session or one-hour/four-hour highs or lows. | 17:00–20:15 |
| E26 02 | Seek five-minute reversal confirmation through BOS or inverse FVG. | 20:30–21:43 |
| E26 03 | Wait for five-minute continuation through FVG fill or equilibrium retracement. | 21:50–23:01 |
| E26 04 | Use one-minute BOS or inverse FVG for entry confirmation. | 23:13–23:25 |
| E26 05 | Avoid conflicting S&P and Nasdaq five-minute trends. | 49:11–51:37 |
| E26 06 | Examples place stops beyond the second high or low; manage intervening targets and partials, with break-even after first profit. | 35:20–46:31 |
| E26 07 | Describes finishing by 10:30 Eastern and declining prolonged chop. | 53:28–55:25 |

“BOS” means break of structure; “FVG” means fair value gap. The exact swing, zone, ordering, reset, target and management definitions remain unresolved. Do not adopt the transcript’s inconsistent reward/risk statistics.

# January 2026 component definitions

These three component lessons have official publication metadata and coherent secondary speech transcripts. Their timestamps remain unverified against audiovisual playback. They clarify their own versions; compatibility with the June strategy must still be established.

**J26 BOS — January 6:** Monitor the most recent relevant swing. A close equal to the reference low fails the break test; the close must be strictly beyond it (04:35–04:48). Wick penetration alone is insufficient (06:12–06:47). The reference low can update while bullish structure remains intact (07:09–09:29). Dojis, equal swing selection, trend initialization and exact pair indexing remain unresolved. [Original](https://www.youtube.com/watch?v=Zzk864cVJek), [speech transcript](https://sozai.app/transcript/path-to-profitability-break-structure/)

**J26 FVG — January 7:** Use three consecutive candles. Bullish boundaries are the first high and third low; bearish boundaries reverse those extremes. First/third candle color is irrelevant; the middle candle supplies direction (04:20–07:20). Overlapping wicks leave no gap. Closing through the adverse boundary invalidates a gap; a wick through does not (16:03–18:07). Same-direction gaps without intervening retracement form a stack. After retracement and continuation beyond the prior extreme, associated gaps are retired, including untouched gaps (24:20–32:14). The speech alternates between a push and a close beyond that extreme, leaving the exact retirement trigger unresolved. [Original](https://www.youtube.com/watch?v=xX5LTSJ5wwM), [speech transcript](https://sozai.app/transcript/path-to-profitability-fair-value-gaps/)

**J26 IFVG — January 9:** Bearish inversion closes below a bullish gap's bottom; bullish inversion closes above a bearish gap's top. Wicks alone do not qualify (08:57; 20:38). In a bullish stack, breaking an upper gap alone does not confirm the intended reversal; the bottom gap must fail (13:51–18:51). IFVG can confirm before BOS, so requiring both changes this teaching (08:00–09:29). The mirrored bearish-stack case and selection across separate impulse groups still need verification. [Original](https://www.youtube.com/watch?v=4sRDnVmLcMk), [speech transcript](https://sozai.app/transcript/path-to-profitability-inverse-fair-value-gaps/)

**Implementation consequence:** Keep individual-gap invalidation, grouped-gap confirmation and gap retirement as separate events. Record each group's formation and availability times. A textbook gap detector is only one component of this reconstruction.

# Earlier versions and material conflicts

## The 2025 integrated guide

The [2025 guide](https://www.youtube.com/watch?v=SHJHpedYh6A), accessed through [Scribe](https://pickscribe.com/v/SHJHpedYh6A/), states an index-entry window of 09:50–10:30 Eastern, with preparation before the open. It allows five-minute BOS, inverse FVG or SMT confirmation; FVG, order block, breaker block or equilibrium continuation; then one-minute BOS or inverse FVG. These are alternatives. One example lets a move serve both confirmation and continuation. It identifies HeroFX as a CFD broker. Whether every option survives into the June 2026 version is unresolved.

Do not merge SMT divergence with trend disagreement: they require separately specified tests. No source-backed TJR-specific CISD rule was recovered in this pass.

## Original Boot Camp structure and entries

**BC23 structure:** Day 6 describes an upward candle followed by a downward candle as a swing high, using the higher of the two wicks; reverse the colors and use the lower wick for a swing low. The most recent relevant swing governs. Reversal confirmation requires a completed candle close beyond its level; a wick-only breach is insufficient. In an uptrend he watches lows, and in a downtrend highs. Dojis, equality, consolidation initialization and same-bar ordering still need resolution. [Original lesson](https://www.youtube.com/watch?v=PmhuPbY8ZHo), [transcript](https://youtubetotranscript.com/transcript?current_language_code=en&v=PmhuPbY8ZHo)

A causal implementation can recognize that two-candle swing only after the second candle closes. That is an engineering consequence of the definition, not permission to substitute a future-confirmed fractal pivot.

**BC23 liquidity:** Day 8 requires a subsequent directional shift rather than entering solely because a level was reached. His explanation about resting or institutional orders is a market narrative; OHLC candles do not establish actual institutional intentions. [Lesson](https://www.youtube.com/watch?v=Lxnu7InGhGE), [transcript](https://youtubetotranscript.com/transcript?current_language_code=en&v=Lxnu7InGhGE)

**BC23 execution variants:** Day 30 offers sweep plus BOS immediately, or retracement through an order block or FVG, optionally adding equilibrium. He tells the learner to choose a model. Day 33 illustrates lower-timeframe confirmation and rejection of a breached gap. These are not instructions to require every confluence on every trade. [Day 30 transcript](https://pickscribe.com/ja/v/ESsy0uoFAz4/), [Day 33 transcript](https://youtubetotranscript.com/transcript?current_language_code=en&v=K8DwhtmvAW8)

**BC23 bias:** Day 34 uses weekly context, daily structure, then four-hour/hourly context and lower-timeframe execution. Conflicting higher-timeframe directions can constrain targets rather than always prohibit a trade. Keep this hierarchy separate from the newer candidate until compatibility is established. [Lesson and transcript](https://youtubetotranscript.com/transcript?current_language_code=en&v=sjuWqKDsQtI)

## Risk and news conflicts

Day 13 initially describes 1–3% per trade, then clarifies a preferred **1–3% total daily risk**, split among setups; no setup means no risk. That is historical educational guidance, not Sideri’s approved budget. The accounting basis—initial committed risk, realized losses, or remaining daily capacity—is not mechanically specified. Do not encode repeated 3% trades from the opening sentence. [Risk lesson](https://www.youtube.com/watch?v=RkMBoqbeUq8), [transcript](https://youtubetotranscript.com/transcript?current_language_code=en&v=RkMBoqbeUq8)

**BC23 trading plan — Day 29:** He describes personal preset sizing, recommends calculated sizing for learners, and usually takes one daily trade, occasionally two with risk allocated within the daily budget. His entry window is the first 1½ hours after the NYSE open; he explicitly distinguishes stopping entries from closing an existing trade. A five-point/five-minute news move is a random illustration, not a fixed threshold. Do not change instruments just to find activity after reaching the plan's limit. This historical plan supplies neither a universal current trade cap nor Sideri's risk budget. [Original, June 24, 2023](https://www.youtube.com/watch?v=065lMUrD_kg), [coherent speech transcript](https://pickscribe.com/fr/v/065lMUrD_kg)

Day 19’s accessible portion says to avoid CPI, PPI, FOMC and NFP days, and wait after other significant releases while evaluating disruption. Waiting examples vary around 15–30 minutes. Later trade commentary includes conditional news-day behavior. This is a version conflict, not grounds to invent a universal current blackout interval. [News lesson](https://www.youtube.com/watch?v=w5sUCqFH3Lg), [partial transcript](https://pickscribe.com/ko/v/w5sUCqFH3Lg)

## Older stop and target material

**BC23 stops — Day 38:** Coherent speech supports protection beyond the liquidity sweep, with a broker/instrument spread allowance. A nearer order-block/FVG stop is a reluctant exception when sweep-based reward/risk is poor; he acknowledges premature stops despite an eventually correct directional bias. The news/preholiday example uses reduced normal size. Exact buffers, exception selection and consistent contract-unit calculations remain unresolved. [Original](https://www.youtube.com/watch?v=1FunNCUw_jM), [speech transcript](https://pickscribe.com/v/1FunNCUw_jM)

Day 37's target rules and Day 53's partial-fraction example still rely on secondary summaries. They support investigating structural targets and a particular 50% first partial, not universal 2R exits or fixed partial fractions. Day 53's original publication date is **July 18, 2023**; the earlier July 19 date came from secondary metadata. [Target lesson](https://www.youtube.com/watch?v=FjSiLFrg5fo), [partial example](https://www.youtube.com/watch?v=Oi_mK1Lt-iQ)

A reported losing example in Day 49 nearly reaches its first target, then stops out. Its commentary also discusses waiting for news and not immediately taking another trade. It is useful for testing false target fills and selective example bias, but is not an independently verified brokerage record. [Original recap](https://www.youtube.com/watch?v=__fKQR5RR08), [transcript](https://lilys.ai/en/notes/226714)

# Decisions that must remain unresolved

The following are implementation questions, not newly discovered TJR rules. Each needs an explicit answer tied to a source version or a separately named experimental interpretation.

| Area | Required definition |
| --- | --- |
| Instruments | Exact analysis symbols and execution products, feed, contract expiry, roll policy, bid/ask/last basis and bar alignment. |
| Structure | Version-specific swing formation, dojis, equal-swing handling, trend initialization and nested structure; January's strict close comparison does not settle all other versions. |
| Liquidity | Eligible levels, session boundaries, minimum breach, same-level retests, age, already-swept levels and competing-pool priority. |
| Zones | Version-specific geometry and inversion, minimum size, displacement, overlap, stack membership, fill depth and retirement timing. |
| Sequence | Which alternatives belong to the chosen version, whether stages share a bar, timeouts and resets after failed confirmation. |
| Alignment | Trend algorithm on each index, synchronized observation times and stale-feed treatment. |
| Orders | Market/limit/stop entry, precise trigger, permitted latency, expiry, cancellation and reentry. |
| Management | Which second swing, stop buffer, target ranking, partial fractions, break-even trigger and cost offset. |
| Sessions | New-entry windows versus forced-exit rules, daylight saving, holidays, news classes and blackout periods. |
| Risk | User-approved cash limits, daily accounting, maximum trades, simultaneous correlated exposure and account restrictions. |
| Discretion | What constitutes chop, poor clarity, exhaustion or a veto; whether it can be observed from the data. |

A missing required definition must produce an explicit blocked decision. It must not silently acquire a common ICT default or a parameter selected because it makes historical results look good.

# Machine readable handoff

This is a specification scaffold, not a working trading model. Null values intentionally prevent an implementation from claiming resolved rules. The New York timezone is an engineering representation of the cited Eastern sessions; individual source windows still need selection and verification.

```json
{
  "schema_version": "1.1",
  "project": "TJR public rule reconstruction",
  "research_date": "2026-10-14",
  "status": "RESEARCH_SPECIFICATION_NOT_VALIDATED",
  "mode": "observe_only",
  "execution_enabled": false,
  "active_strategy_version": null,
  "candidate_version": "UPDATED_2026_06",
  "candidate_source_video": "8PYgFVB0GHE",
  "existing_bot_market": "prediction_markets",
  "prediction_market_translation": "separate_unvalidated_strategy",
  "reference_market": {
    "symbols": [],
    "vendor": null,
    "price_type": null,
    "bar_alignment": null
  },
  "execution_market": {
    "product_type": null,
    "venue": null,
    "symbol": null,
    "expiry": null,
    "roll_policy": null,
    "tick_size": null,
    "point_value": null
  },
  "timing": {
    "timezone": "America/New_York",
    "entry_window_start": null,
    "entry_window_end": null,
    "session_boundaries": null,
    "news_filter": null,
    "force_flat_at": null
  },
  "rules": {
    "swing_definition": null,
    "trend_initialization": null,
    "liquidity_pool_selection": null,
    "sweep_test": null,
    "five_minute_reversal": null,
    "continuation_zone_selection": null,
    "one_minute_entry": null,
    "cross_index_alignment": null,
    "stage_expiration_and_reset": null,
    "fvg_geometry": null,
    "fvg_eligibility": null,
    "fvg_stack_membership": null,
    "fvg_retirement": null
  },
  "orders": {
    "entry_type": null,
    "entry_price_rule": null,
    "cancel_rule": null,
    "stop_rule": null,
    "stop_buffer": null,
    "target_selection": null,
    "partial_fractions": null,
    "breakeven_trigger": null,
    "breakeven_cost_offset": null
  },
  "risk": {
    "approved_per_trade_dollars": null,
    "approved_daily_loss_dollars": null,
    "daily_accounting_convention": null,
    "max_trades": null,
    "simultaneous_exposure": null,
    "margin_and_drawdown_rules": null
  },
  "evidence": {
    "visual_review_completed": false,
    "complete_public_inventory": false,
    "complete_tweet_archive": false,
    "newer_videos_pending": [
      "Xdu6j2E1DEI",
      "FBX-gtFGWyU",
      "TYbpk7WogHI"
    ],
    "newer_video_coverage": {
      "Xdu6j2E1DEI": "SECONDARY_SUMMARY_WITH_CONTRADICTION",
      "TYbpk7WogHI": "ORIGINAL_SPEECH_UNAVAILABLE",
      "FBX-gtFGWyU": "ORIGINAL_SPEECH_UNAVAILABLE"
    }
  },
  "on_unresolved_required_field": "BLOCK_WITH_REASON",
  "on_missing_or_stale_data": "BLOCK_WITH_REASON",
  "rule_registry": {
    "records": [],
    "require_source_version": true,
    "allow_cross_version_inheritance": false,
    "on_unverified_required_rule": "BLOCK_STRATEGY_DECISION"
  }
}
```

## Rule evidence records

Every implemented predicate needs its own evidence record. Use `rule_id`, `source_video_id`, `source_url`, `speech_locator`, `locator_verified`, `retrieved_at_utc`, `evidence_grade`, `source_version`, `applies_to_versions`, `operational_definition`, `unresolved_edges`, `test_case_ids` and `implementation_status`. Missing locators remain null. A summary and a transcript mirror of the same video share one source identity.

Keep evidence grade separate from code status: a passing synthetic test does not upgrade a transcript to chart-verified evidence. Distinguish instructional examples, retrospective recaps, visible live decisions and broker fills. Never infer a fill from a drawn entry arrow. The January component lessons below do not automatically supply missing June-model rules.

The active strategy remains null. Features may be explored in isolated research tests, but a complete strategy decision requires every applicable rule to have an explicit definition and selected-version compatibility. A configuration change must record its reason and invalidate the affected prior validation; it cannot silently inherit another version's choices.

# Implementation architecture

These are proposed engineering requirements.

1. **Source register:** retain video ID, title as retrieved, original publication date, trade/example date, retrieval time, text provider, coverage, integrity flags, source locators and strategy version. A mirror’s ingest date is not a publication date.

2. **Data adapter:** retain raw events and corrected versions separately; capture event time and arrival time, exact instruments, exchange calendar and data gaps. Build higher-timeframe bars from a documented alignment convention.

3. **Feature layer:** implement only the selected definitions; record the time each level became knowable. Keep chart-derived candidates separate from observed order-book facts.

4. **Strategy layer:** evaluate a frozen version and emit a rule trace. Separate “not a setup” from “unable to assess.” Do not let future prices or hindsight labels change past decisions.

5. **Observation ledger:** append immutable entry, cancellation, stop, target, partial and pass intentions with data/configuration hashes. No order endpoint is needed for this stage.

6. **Paper execution model:** use contemporaneous bid/ask and conservative fill logic, documented latency, fees, slippage, gaps, partial fills and cancellation races. Where a bar touches both stop and target without sequencing evidence, preserve ambiguity or use a declared adverse assumption.

7. **Future execution adapter:** only after separately authorized implementation, verified broker capabilities and account constraints. It must reconcile acknowledgments, fills, positions, protective orders, restarts and duplicate events.

Suggested event fields:

```json
{
  "strategy_version": null,
  "event_time_utc": null,
  "observed_at_utc": null,
  "analysis_instrument": null,
  "execution_instrument": null,
  "input_snapshot_hash": null,
  "configuration_hash": null,
  "decision": "BLOCKED_UNRESOLVED",
  "action": "NONE",
  "entry": null,
  "stop": null,
  "targets": [],
  "quantity": null,
  "rule_ids": [],
  "source_ids": [],
  "unresolved_fields": [],
  "counterfactual_or_hindsight": false
}
```

For a futures adapter, planned per-contract stop risk is the absolute entry-to-stop distance times point value, plus modeled costs. Any quantity calculation also needs an approved cash budget, margin and account limits. Stop risk is an estimate; gaps and execution can exceed it. Do not derive position size from a promotional dollar-profit figure or from the bot’s old binary-contract quantity.

# Fidelity and outcome validation

Behavioral fidelity and profitability are different tests. A profitable adaptation may fail to match TJR; a close match may still lose after costs.

| Test | Required evidence |
| --- | --- |
| Corpus selection | Choose complete sessions and inclusion rules before inspecting outcomes; include losses and explicit passes. Preserve inaccessible or unlabelable sessions in coverage counts. |
| Ground truth | Independently annotate visible entries, directions, chart context, cancellations, stops, targets and management. Record ambiguous interpretations and the timing/price resolution available. |
| Causality | Append future data and verify earlier outputs remain unchanged. Delay swing recognition until confirmation. Do not use a completed higher-timeframe candle before its close. |
| Clock correctness | Test New York daylight-saving transitions, session boundaries, exchange holidays and early closes. Use the historical news calendar as known then. |
| Fill realism | Do not equate a candle touch with a guaranteed limit fill. Preserve spreads, fees, latency, unfilled and partial orders, stop gaps and same-bar ambiguity. |
| Version control | Freeze rule choices and tolerances before holdout evaluation. A changed definition creates a new version and cannot erase the previous result. |
| Operational behavior | Test missing/stale data, out-of-order events, reconnects, restart persistence, duplicate events and deterministic replay. |
| Outcome study | Use chronological development and untouched holdout windows; report all trades, net results, drawdown, uncertainty, exposure and cost sensitivity. Never tune on the holdout. Reusing it makes it development data and requires a new untouched holdout. |

Measure entry precision and recall, direction agreement, timing error, price error in ticks, stop/target differences, cancellation and management agreement, and false trades on explicit passes. Report per-session coverage and unresolved labels. A high “no trade” accuracy is not proof of faithful trading.

## Session labels and scoring

Label decisions as `VISIBLE_TRADE`, `EXPLICIT_PASS`, `UNOBSERVED` or `AMBIGUOUS`. A missing trade in an edited video is not an explicit pass. Record chart instrument, session date, observable decision time, video locator, available price/time resolution and whether the label comes from a live decision or retrospective narration. Keep inferred order intentions separate from observed fills.

Freeze a one-to-one matching procedure and direction, time and price tolerances before scoring. Each predicted entry and observed entry can match once. Report matched entries, unmatched bot entries, missed observed entries and unresolved exclusions; do not discard unlabelable sessions from the coverage denominator. Score exits and partial quantities only where they are observable. Use held-out complete sessions to assess fidelity; selected teaching screenshots can test concepts but cannot establish session-level agreement.

Useful primary implementation references explain [repainting and hindsight pivots](https://www.tradingview.com/pine-script-docs/concepts/repainting/) and [broker-emulator assumptions and testing biases](https://www.tradingview.com/pine-script-docs/concepts/strategies/). Their platform mechanics are examples of failure modes, not evidence that a TJR strategy is profitable.

**Executed synthetic checks: 26 of 26 passed.** They exercise the isolated BC23 feature harness below. No historical TJR-session replay, profitability backtest, broker integration or live execution has been completed.

## Executable synthetic checks

This is our narrow feature test, using invented integer-tick bars and externally supplied trend/level fixtures. It is separate from the January and June models. BC23 equality remains blocked; January's explicit equal-close rule has not been silently imported. Availability timestamps, blocking, and context reseeding are engineering choices, not TJR rules. The conservative guard requires the active level to be available before the current bar starts. After a break or unresolved input, the regression runner requires a fresh audited context; it does not infer a recovery policy.

Run the JavaScript in a compatible runtime; append `console.log(report)` to display case results. Assertions throw on failure. The code has no market-data or order connection.

```js
// Synthetic BC23 feature/close-break harness. No strategy, market data or orders.
// Source: Day 6, https://www.youtube.com/watch?v=PmhuPbY8ZHo (secondary transcript).
// Price values are integer ticks. Context is an externally supplied TEST fixture.
// WAIT/BLOCKED behavior, arrival timestamps and reseeding are engineering guards.
const block = (reason, extra = {}) => ({status:"BLOCKED", reason, ...extra});
function inspectBC23(a,b,ctx,now) {
  const bars=[a,b], p=["o","h","l","c"];
  if (!Number.isFinite(now)) return block("INVALID_DECISION_TIME");
  if (bars.some(x=>!x || p.some(k=>!Number.isInteger(x[k])) ||
      !Number.isFinite(x.start)||!Number.isFinite(x.end)||!Number.isFinite(x.arrival)||
      x.end<=x.start||x.arrival<x.end||x.h<Math.max(x.o,x.c)||x.l>Math.min(x.o,x.c)||x.h<x.l))
    return block("INVALID_BAR");
  if (bars.some(x=>!x.closed || x.end>now || x.arrival>now)) return {status:"WAIT",reason:"BAR_NOT_AVAILABLE"};
  if (a.symbol!==b.symbol || !a.symbol) return block("MIXED_INSTRUMENT");
  if (a.id===b.id || a.end!==b.start) return block("NONADJACENT_OR_DUPLICATE");
  const color=x=>Math.sign(x.c-x.o), ca=color(a), cb=color(b);
  if (!ca||!cb) return block("DOJI_RULE_UNRESOLVED");
  const side=ca===1&&cb===-1?"high":ca===-1&&cb===1?"low":null;
  const swing=side?{side,price:side==="high"?Math.max(a.h,b.h):Math.min(a.l,b.l),
    pair:[a.id,b.id],knownAt:b.end,availableAt:b.arrival}:null;
  if (!ctx || !["up","down"].includes(ctx.trend) || !ctx.active)
    return block("INITIAL_CONTEXT_UNRESOLVED",{swing});
  const s=ctx.active, expected=ctx.trend==="up"?"low":"high";
  if (s.side!==expected || !Number.isInteger(s.price)||!Number.isFinite(s.knownAt)||
      !Number.isFinite(s.availableAt)||s.availableAt<s.knownAt||s.knownAt>a.end||s.availableAt>b.start)
    return block("ACTIVE_LEVEL_INVALID_OR_NOT_YET_AVAILABLE",{swing});
  if (b.c===s.price) return block("BC23_EQUAL_CLOSE_UNRESOLVED",{swing});
  const broke=expected==="high"?b.c>s.price:b.c<s.price;
  if (broke&&swing&&swing.side===expected)
    return block("SAME_BAR_LEVEL_UPDATE_AND_BREAK_UNRESOLVED",{swing});
  return {status:"OBSERVATION",swing,bos:broke?{direction:expected==="high"?"up":"down",
    level:s.price,knownAt:b.end,availableAt:b.arrival}:null,
    nextContext:broke?null:{trend:ctx.trend,active:swing&&swing.side===expected?swing:{...s}},
    reseedRequired:broke,executionEnabled:false};
}
const B=(id,t,o,h,l,c)=>({id,symbol:"SYNTHETIC",start:t,end:t+1000,arrival:t+1000,closed:true,o,h,l,c});
const C=(trend,price)=>({trend,active:{side:trend==="up"?"low":"high",price,knownAt:0,availableAt:0}});
const high=[B("a",0,100,108,99,104),B("b",1000,104,107,101,102)];
const low=[B("a",0,104,106,99,101),B("b",1000,101,105,98,103)];
const bull=[B("a",0,100,103,99,102),B("b",1000,102,108,101,106)];
const bear=[B("a",0,105,106,102,103),B("b",1000,103,104,98,99)];
const wick=[bull[0],B("b",1000,102,108,101,104)];
const eq=[bull[0],B("b",1000,102,108,101,105)];
const inspect=(pair,ctx=C("down",110),now=2000)=>inspectBC23(...pair,ctx,now);
let results=[];
function test(name,fn){try{if(fn()!==true)throw Error("assertion");results.push({name,pass:true});}catch(e){results.push({name,pass:false,error:e.message});}}
test("two-candle high uses larger wick",()=>inspect(high).swing.price===108);
test("two-candle low uses smaller wick",()=>inspect(low,C("up",90)).swing.price===98);
test("same colors produce no swing",()=>inspect(bull,C("down",110)).swing===null);
test("wick-only breach produces no BOS",()=>inspect(wick,C("down",105)).bos===null);
test("strict close above observes upward BOS",()=>inspect(bull,C("down",105)).bos.direction==="up");
test("strict close below observes downward BOS",()=>inspect(bear,C("up",100)).bos.direction==="down");
test("break never creates order and requires reseed",()=>{const r=inspect(bull,C("down",105));return r.executionEnabled===false&&r.reseedRequired&&r.nextContext===null;});
test("BC23 exact equality is unresolved",()=>inspect(eq,C("down",105)).reason==="BC23_EQUAL_CLOSE_UNRESOLVED");
test("doji blocks rather than being skipped",()=>inspect([high[0],B("b",1000,103,108,101,103)]).reason==="DOJI_RULE_UNRESOLVED");
test("forming second candle cannot confirm swing",()=>inspect([high[0],{...high[1],closed:false}]).status==="WAIT");
test("closed data cannot be read before close",()=>inspect(high,C("down",110),1999).status==="WAIT");
test("late arrival is unavailable until arrival",()=>inspect([high[0],{...high[1],arrival:2100}],C("down",110),2000).status==="WAIT");
test("swing knowledge time is second close",()=>inspect(high).swing.knownAt===2000);
test("missing trend context blocks",()=>inspect(high,null).reason==="INITIAL_CONTEXT_UNRESOLVED");
test("same-bar replacement and old-level break blocks",()=>inspect([B("a",0,101,105,100,104),B("b",1000,108,109,105,106)],C("down",105)).reason==="SAME_BAR_LEVEL_UPDATE_AND_BREAK_UNRESOLVED");
test("future-known active level blocks",()=>inspect(high,{trend:"down",active:{side:"high",price:110,knownAt:2000,availableAt:2000}}).reason==="ACTIVE_LEVEL_INVALID_OR_NOT_YET_AVAILABLE");
test("invalid decision time blocks",()=>inspect(high,C("down",110),NaN).reason==="INVALID_DECISION_TIME");
test("impossible level availability blocks",()=>inspect(high,{trend:"down",active:{side:"high",price:110,knownAt:500,availableAt:0}}).reason==="ACTIVE_LEVEL_INVALID_OR_NOT_YET_AVAILABLE");
test("nonadjacent bars block",()=>inspect([high[0],{...high[1],start:1200}]).reason==="NONADJACENT_OR_DUPLICATE");
test("mixed symbols block",()=>inspect([high[0],{...high[1],symbol:"OTHER"}]).reason==="MIXED_INSTRUMENT");
test("malformed OHLC blocks",()=>inspect([high[0],{...high[1],h:100}]).reason==="INVALID_BAR");
test("noninteger tick prices block",()=>inspect([high[0],{...high[1],c:102.5}]).reason==="INVALID_BAR");
test("inputs are not mutated",()=>{const ctx=C("down",110),before=JSON.stringify([high,ctx]);inspect(high,ctx);return before===JSON.stringify([high,ctx]);});
test("unambiguous latest relevant swing is retained",()=>inspect(high).nextContext.active.price===108);
function replay(bars,seed){let ctx=seed,log=[];for(let i=1;i<bars.length;i++){const r=inspectBC23(bars[i-1],bars[i],ctx,bars[i].arrival);log.push(r);ctx=r.status==="OBSERVATION"?r.nextContext:null;}return log;}
test("appended future cannot alter prior output",()=>{const r=replay(high,C("down",110)),all=replay([...high,B("c",2000,102,106,101,105)],C("down",110));return JSON.stringify(r)===JSON.stringify(all.slice(0,r.length));});
test("causal replay is deterministic",()=>JSON.stringify(replay(high,C("down",110)))===JSON.stringify(replay(high,C("down",110))));
const report={scope:"synthetic BC23 feature semantics only; no historical profitability",passed:results.filter(x=>x.pass).length,total:results.length,results};
if(results.some(x=>!x.pass))throw Error(JSON.stringify(report));
```

| Later component | Required case, not tested by this harness |
| --- | --- |
| Stage order | Shared-bar stages require selected-version permission and evidence of the event order. |
| Higher timeframe | A completed 10:00–10:05 candle cannot affect a 10:03 decision; also respect arrival time. |
| Signal versus fill | A close-time signal cannot receive an earlier open, low or high as its entry fill. |
| Partial entry | Two fills on a five-contract intention create two held and three pending contracts. |
| Cancellation | A cancel request is not an acknowledgement; reconcile intervening fills. |
| Partial exit | Reduce actual position and protective quantities once per unique fill. |
| Stop and target | Preserve unknown intrabar ordering or declare an adverse assumption. |
| Restart | Reconstruct acknowledged positions and pending orders without resubmitting duplicates. |

# Source identity and coverage

The identity chain connects [TJR’s profile hub](https://link.me/tjr), [YouTube @TJRTrades](https://www.youtube.com/@TJRTrades), [the company website](https://www.tjrtrades.com/) and [X @_TJRTrades](https://x.com/_TJRTrades). Direct X access failed; only three limited third-party post mirrors were inspected, with attribution/timing defects. They do not supply a verified tweet archive or operational risk policy.

The [jointjrtrades.com disclaimer](https://www.jointjrtrades.com/disclaimer) describes an independent affiliate; it is excluded as a primary rule source. AI summaries, transcript mirrors and multiple copies of the same video are not independent confirmations.

Official marketing and [company disclosures](https://www.tjrtrades.com/full-disclosure) do not provide a complete independently verified trading ledger. None was located in this pass. [Whop’s case study](https://whop.com/blog/how-tjr-trades-20xd-revenue-in-8-months-after-switching-to-whop/) concerns an education business; those revenues cannot be substituted for brokerage returns. This is an evidence distinction, not a conclusion about TJR’s personal profitability.

In the catalogue, **primary metadata** means the date was corroborated in an indexed official YouTube result; it does not mean the video was watched. A coherent transcript is still a third-party text representation. Money figures retained in titles are creator claims.

| Video | Publication date and evidence | Coverage |
| --- | --- | --- |
| [My Trading Strategy](https://www.youtube.com/watch?v=T-Bo-9GDi3s) | 2023-01-16; primary metadata | metadata only |
| [Boot Camp Day 1 Take Action](https://www.youtube.com/watch?v=Xq6-oO2n6-U) | 2023-05-26; primary metadata | metadata and transcript excerpt |
| [Boot Camp Day 6 Break of Structure](https://www.youtube.com/watch?v=PmhuPbY8ZHo) | 2023-05-31; secondary date | coherent transcript text |
| [Boot Camp Day 8 Liquidity part 1](https://www.youtube.com/watch?v=Lxnu7InGhGE) | 2023-06-02; primary metadata | coherent transcript text |
| [Boot Camp Day 13 Risk Management](https://www.youtube.com/watch?v=RkMBoqbeUq8) | 2023-06-07; primary metadata | coherent transcript text |
| [Boot Camp Day 14 Fair Value Gaps](https://www.youtube.com/watch?v=d0AxLACYaqU) | 2023-06-08; primary metadata | coherent transcript text |
| [Boot Camp Day 18 Fair Value Gaps](https://www.youtube.com/watch?v=qecF411R83s) | 2023-06-12; secondary date | coherent transcript text |
| [Boot Camp Day 19 News](https://www.youtube.com/watch?v=w5sUCqFH3Lg) | 2023-06-13; secondary date | substantial transcript prefix |
| [Boot Camp Day 20 Order Blocks](https://www.youtube.com/watch?v=qhuFg_OXdmE) | 2023-06-14; secondary date | preview and summary |
| [Boot Camp Day 29 Trading Plan](https://www.youtube.com/watch?v=065lMUrD_kg) | 2023-06-24; primary metadata | coherent transcript text |
| [Boot Camp Day 30 Execution](https://www.youtube.com/watch?v=ESsy0uoFAz4) | 2023-06-25; primary metadata | coherent transcript text |
| [Boot Camp Day 33 Execution part 3](https://www.youtube.com/watch?v=K8DwhtmvAW8) | 2023-06-28; primary metadata | coherent transcript text |
| [Boot Camp Day 34 Daily Bias](https://www.youtube.com/watch?v=sjuWqKDsQtI) | 2023-06-29; primary metadata | coherent transcript text |
| [Boot Camp Day 37 Taking Profits](https://www.youtube.com/watch?v=FjSiLFrg5fo) | 2023-07-02; secondary date | summary and description |
| [Boot Camp Day 38 Stop Losses](https://www.youtube.com/watch?v=1FunNCUw_jM) | 2023-07-03; primary metadata | coherent transcript text |
| [Boot Camp Day 39 Calculating Lot Size](https://www.youtube.com/watch?v=KSiWKfPOlh4) | 2023-07-04; primary metadata | secondary summary |
| [Boot Camp Day 49 Loss Recap](https://www.youtube.com/watch?v=__fKQR5RR08) | 2023-07-14; primary metadata | timestamped transcript text |
| [Boot Camp Day 53 Daily Bias and GBPJPY Recap](https://www.youtube.com/watch?v=Oi_mK1Lt-iQ) | 2023-07-18; primary metadata | secondary summary; publication date corrected |
| [Boot Camp 2.0](https://www.youtube.com/watch?v=o_SdawM3DIE) | 2023-08-23; primary metadata | metadata only |
| [My New Day Trading Strategy Revealed](https://www.youtube.com/watch?v=M6DQKMp-3Vo) | 2023-09-05; primary metadata | metadata only |
| [Trading Transformation Day 1 My Purpose](https://www.youtube.com/watch?v=HlllJ9YH3Qw) | 2024-02-07; primary metadata | excerpt and summary |
| [Trading Transformation Day 8 Break of Structure](https://www.youtube.com/watch?v=nR9Iikd6V2s) | 2024-02-18; primary metadata | metadata and secondary notes |
| [Trading Transformation Day 14 Order Blocks part 1](https://www.youtube.com/watch?v=uRXKBX1kzwc) | 2024-02-27; secondary date | metadata only |
| [Trading Transformation Day 20 Equilibrium part 2](https://www.youtube.com/watch?v=vrGMaYeMJCg) | 2024-03-08; secondary date | metadata only |
| [Trading Transformation Day 33 Inverse FVGs](https://www.youtube.com/watch?v=rMkghkG-ZjE) | 2024-05-06; primary metadata | transcript excerpt |
| [Break of Structure Explained](https://www.youtube.com/watch?v=n97MKj6wGFk) | 2024-11-19; primary metadata | preview and secondary summary |
| [Fair Value Gaps Explained](https://www.youtube.com/watch?v=xcDOMKaOIsk) | 2025-02-03; primary metadata | preview and secondary summary |
| [The Science Based Trading Strategy That Made Me 291456 This Month](https://www.youtube.com/watch?v=KxBRLErkel0) | 2025-05-26; secondary date | metadata and summary excerpt |
| [The Stupid Simple Strategy That Makes Me 156943 Per Month](https://www.youtube.com/watch?v=BMyeYQIj_vU) | 2025-09-17; primary metadata | substantial secondary summary |
| [How To Start Day Trading As A Beginner In 2026 9 hours](https://www.youtube.com/watch?v=aobHuNcI1QM) | 2025-09-25; primary metadata | caption mirror excerpt |
| [Path to Profitability Break of Structure Explained](https://www.youtube.com/watch?v=Zzk864cVJek) | 2026-01-06; primary metadata | substantial coherent speech transcript |
| [Path to Profitability Fair Value Gaps Explained](https://www.youtube.com/watch?v=xX5LTSJ5wwM) | 2026-01-07; primary metadata | substantial coherent speech transcript |
| [Path to Profitability Inverse Fair Value Gaps Explained](https://www.youtube.com/watch?v=4sRDnVmLcMk) | 2026-01-09; primary metadata | substantial coherent speech transcript |
| [How To Start Day Trading In 2026 Full Tutorial](https://www.youtube.com/watch?v=yiuFUp0kFz8) | 2026-05-07; primary metadata | partial caption mirror |
| [My UPDATED Day Trading Strategy 2026](https://www.youtube.com/watch?v=8PYgFVB0GHE) | 2026-06-05; primary metadata | secondary transcript with integrity defects |
| [Once You Learn Price Action Trading Becomes Embarrassingly Simple](https://www.youtube.com/watch?v=Xdu6j2E1DEI) | 2026-10-02; secondary date | secondary summary with internal contradiction |
| [How To Find Daily Bias](https://www.youtube.com/watch?v=FBX-gtFGWyU) | 2026-10-07; secondary date | unavailable |
| [Learn Every Trading Confluence In 18 Minutes](https://www.youtube.com/watch?v=TYbpk7WogHI) | 2026-10-12; secondary date | unavailable |
| [Boot Camp 2.0 Day 11 Where to Take Profit](https://www.youtube.com/watch?v=6zXKK3Wrusg) | Unverified; date pending | secondary summary |
| [Boot Camp Day 54 Daily Bias and No Trades Today](https://www.youtube.com/watch?v=9sD9kTia4V4) | Unverified; date pending | secondary summary |
| [Older How To Find Daily Bias](https://www.youtube.com/watch?v=e_FV0Q14k8E) | Unverified; date pending | substantial transcript text |
| [Beginners Guide To Start Day Trading In 2025](https://www.youtube.com/watch?v=SHJHpedYh6A) | Unverified; date pending | coherent transcript sections |
| [The Only Fair Value Gap Video You Need](https://www.youtube.com/watch?v=qswlc-I-DuA) | Unverified; date pending | coherent transcript text; date unverified |

# Priority work before coding the strategy

1. Obtain original speech and chart evidence for the October candidates [confluences](https://www.youtube.com/watch?v=TYbpk7WogHI), [daily bias](https://www.youtube.com/watch?v=FBX-gtFGWyU) and [price action](https://www.youtube.com/watch?v=Xdu6j2E1DEI). The [price-action summary](https://skip.watch/en/Xdu6j2E1DEI) contains contradictory order-direction descriptions and is unsuitable for resolving rules. June is not claimed to be the latest current model.

2. Verify the June strategy’s spoken rules against chart frames, especially index symbols, swing selection, entries and management. Correct the transcript’s reordered passages without inventing missing words.

3. Choose one dated version. Resolve its required definitions and record any engineering interpretations separately.

4. Establish the exact instrument/feed and evaluate available paper-data and broker adapters. Inspect the receiving bot’s architecture before proposing files or integration points.

5. Build a complete-session labeled corpus, freeze behavioral tolerances and a chronological test protocol, then implement replay and observation. The absence of visible passes or execution records limits claims of fidelity.

6. Evaluate net outcomes only after behavioral and data-integrity checks. Live activation requires a separately concrete review of the actual implementation, account constraints and requested risk; this handoff supplies none of those approvals.

# Copy into the receiving ChatGPT session

```text
Use the attached TJR strategy research and bot handoff as a source register and research specification, not a validated strategy or proof of complete coverage.

Sideri wants a faithful reconstruction of TJR's documented public trading behavior. The existing bot currently connects to prediction markets. Preserve its current strategy, credentials, orders, records and account limits. Do not treat a binary event-contract adaptation as exact TJR replication.

Inspect the bot repository and current instructions. Separate chart/reference markets from the execution product. Start with offline replay or observation only. Do not connect, fund or enable a new live trading account from this research handoff.

Keep BC23, the 2025 guide, January 2026 component lessons and the June 2026 candidate separate. Review the pending October videos before calling June the latest version. Verify chart footage and original speech; source mirrors have defects. Every operational rule needs a machine-readable evidence record and a source/version or an explicit experimental-interpretation label. Component rules cannot silently migrate across versions. Unresolved required fields block affected decisions.

Use the companion MNQ research prototype's actual saved code and tests when implementing that separate experimental subset. Its 65 synthetic checks do not establish historical returns or exact TJR fidelity. Keep its frozen development/holdout periods and explicit engineering choices intact; retrieve the complete companion rather than reconstructing code from a summary.

Create the source registry, causal feature definitions, event ledger and versioned replay interface. Re-run the included synthetic checks; their passing result is not historical behavioral validation. Missing footage is UNOBSERVED, not an explicit no-trade decision. Resolve risk, order, stop, target, session and news semantics before implementing signal execution. Never invent universal 1% risk, 2R exits, two trades per day, or partial percentages.

Freeze complete-session development and holdout cohorts before testing. Measure behavioral agreement separately from net profitability, including losses, passes, costs, fill uncertainty and all exclusions. Report exactly what was read, implemented, run, saved and still unavailable. Do not claim to be TJR, to trade exactly like him, or to match his profits.
```
