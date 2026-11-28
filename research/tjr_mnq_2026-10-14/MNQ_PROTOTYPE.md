This is Sideri's runnable research prototype for one explicitly defined TJR-inspired experiment. It is an experimental subset of the older Boot Camp sweep/BOS approach, not a reconstruction of all TJR discretion. The original [source handoff](https://chatgpt.com/space/page_d0294998a7cc8191b771278fbfb98a2f) retains the broader evidence and unresolved rules.

Frozen research definition: 2026-10-14 15:28:20 UTC. No historical market bars or outcomes were retrieved for this campaign before freezing. **65 synthetic checks passed; zero historical trades tested; live paper trading has not started.** The execution workspace failed, and the available tools could execute isolated JavaScript but could not download/unpack the offered historical sample or connect an authorized futures feed. No broker orders, account creation, funding or paid data requests occurred.

# Frozen experiment

| Item | Fixed choice |
| --- | --- |
| Version | TJR_BC23_MNQZ25_SWEEP_BOS_v0.1 |
| Instrument | Actual December 2025 MNQ contract, canonical research ID MNQZ2025; provider symbol must be verified. No continuous or adjusted series. |
| Mechanics | $2 per index point; 0.25-point tick = $0.50. One contract is a research accounting unit, not a recommended live stake. |
| Development | September 22 through October 31, 2025. |
| Analyst-unseen holdout | November 3 through December 12, 2025. No outcomes accessed. |
| Reference levels | Immediately preceding cash session's 09:30–16:00 New York high and low on the same contract. Skip shortened/incomplete prior sessions; never silently substitute an older full day. |
| Session | Current features start at 09:30 New York. Require 390 consecutive one-minute bars for a complete regular-session result. The calendar adapter must verify sessions, holidays and early closes. |
| Structure | Two opposite-color adjacent candles form a wick-defined swing. Doji pairs create no swing and are not bridged. Equal-price swings remain chronological observations. |
| Approach | Before the first prior-range breach, two latest highs and two latest lows must both descend for a long reversal, or both ascend for a short. |
| Attempt | The first strict breach of either prior boundary consumes the only candidate attempt, even if trend is unestablished. A dual-boundary breach or an exact touch of the opposite boundary rejects the session. |
| Confirmation | A later candle must strictly close beyond the most recent opposing swing known before that candle. The newly completed pair is processed afterward. |
| Expiry | Confirmation within the next 15 candles; same-side extension updates the extreme without restarting the clock. Reaching the opposite boundary cancels. |
| Entry delay | Signal on bar i queues entry at bar i+2 open: one full minute passes after the signal closes. This is a fixed latency approximation. Fill must occur before 11:00 New York. |
| Pending cancellation | The intervening delay bar touching the frozen stop or target cancels. Reject a gap or modeled friction that invalidates entry geometry. |
| Protection | Stop one tick beyond the most adverse sweep-through-confirmation extreme; target the opposite prior-session boundary. |
| Management | One filled trade maximum; no partials, break-even moves or pyramiding. Force exit at 11:30 New York open. |
| Explicit omission | No news, higher-timeframe bias, ES alignment or discretionary clarity filter in this baseline. |

The component lineage is [Day 6 structure](https://www.youtube.com/watch?v=PmhuPbY8ZHo), [Day 29 planning](https://www.youtube.com/watch?v=065lMUrD_kg), [Day 30 execution variants](https://www.youtube.com/watch?v=ESsy0uoFAz4) and [Day 38 stops](https://www.youtube.com/watch?v=1FunNCUw_jM). **The completed parameter set, trend formula, level choice, candidate cap, delay, expiry, buffer, target and time exit are our preregistered engineering hypotheses.** They have not been attributed to TJR as exact personal rules. Contract mechanics: [CME specifications](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html).

# Execution and cost assumptions

The simulator consumes trade OHLC in integer ticks. It applies adverse friction to market entries, stops and time exits. Opening gaps are processed before intrabar extrema; an opening trade-through of a resting target precedes a later same-bar stop. With unknown intrabar ordering, stop wins and the trade is flagged ambiguous. Targets need one tick of trade-through, then fill at the target without price improvement. These assumptions cannot establish queue position or actual fills.

Real fees and spreads remain unknown. The nine sensitivity scenarios combine hypothetical per-side fees of $0.50, $1.00 and $1.50 with 1, 2 and 4 ticks of aggregate aggressive-fill friction. They are not broker quotes or measured spread distributions. Report every scenario. Platform/data costs must also be subtracted when evaluating actual business profitability. Do not double-charge spread if a later model uses observed bid/ask.

An incomplete or invalid session retains its observed signals/trades but has null session net P&L. The summary separates planned calendar exclusions from blocked, invalid and incomplete sessions; it also counts completed trades retained on unresolved days separately. Drawdown is measured only at completed-session endpoints, not intratrade equity. The code deliberately never sets performanceClaimAllowed to true. Caller-supplied manifest flags are assertions requiring independent evidence, not proof created by the program. Bar availability is an explicit bar-close assumption, not observed feed latency. Opening exits carry a simulated timestamp; intrabar exits retain an uncertain one-minute interval.

# Historical data status and acquisition

| Source checked | Result |
| --- | --- |
| [FirstRate MNQ](https://firstratedata.com/i/futures/MNQ) | Individual contracts offered; public sample ZIP could not be opened by available tools. Sample period is September 21–October 2, 2026, outside this campaign. |
| [Portara MNQ](https://portaracqg.com/futures/int/mnq) | Individual-contract history offered; no raw sample retrieved from its dynamic download interface. |
| [Databento setup](https://databento.com/docs/quickstart/set-up) | Licensed API access/key required; none available here. No authenticated request made. |
| [Public GitHub MNQ file](https://github.com/axb0306/cme-futures-ohlc/blob/main/MNQ/MNQ_1min_20260120_20260415.csv) | No usable raw content retrieved. Historical contract identity and redistribution provenance unverified; rejected for this study. |

Acquire the exact MNQ December 2025 instrument, including the preceding September 19 session, for the frozen windows. A candidate Databento route is GLBX.MDP3 with raw_symbol; resolve candidate MNQZ5 against instrument definitions before accepting that mapping. Obtain one-minute bars plus MBP-1 when possible. Preserve vendor, license, immutable raw files, SHA-256, original timestamps, instrument IDs, adjustment status and missing intervals.

Databento's [OHLCV convention](https://databento.com/docs/schemas-and-data-formats/ohlcv) timestamps intervals at their start and omits intervals with no trade. Do not forward-fill those omissions as observed candles. Normalize prices to exact 0.25-point ticks, preserving raw values. Its aggregation clock may differ from TJR's chart feed. [MBP-1](https://databento.com/docs/schemas-and-data-formats/mbp-1) supplies trades and best bid/ask data but cannot prove a limit-order queue fill.

The saved manifest intentionally contains null hashes, symbols and costs because no dataset or account quote was obtained. Do not replace these with guessed values.

# Historical evaluation protocol

Preserve this version before examining returns. Debug using synthetic cases and development sessions only. An inspected final-test interval cannot remain untouched after it informs a rule change. This holdout is analyst-unseen; that does not prove the educator never used those dates. Keep an attempts log and obtain a new untouched interval after any holdout-driven revision.

Load all scheduled sessions, including no-trade, missing and excluded dates. Verify calendar coverage independently; the code cannot discover omitted sessions from an incomplete input list. Run each cohort separately with every predeclared cost scenario. Report trade count, daily gross/net research dollars, no-trade days, rejected candidates, unresolved dates, ambiguity count, session-end drawdown and loss streak. Report uncertainty and profit concentration by session. Do not give percentage returns without a capital denominator.

No full-session audiovisual TJR label corpus has been obtained. Profitability testing of this experimental subset and fidelity to TJR remain distinct studies. No historical performance number is currently available.

# Paper trading readiness

**Not started.** The code below is an offline OHLC simulator, not a broker adapter or a live process. The fixed December 2025 contract is expired; it must never be used as today's live instrument. A forward study needs a separately dated protocol, verified current actual contract and roll calendar, licensed feed, persistent runtime and the receiving bot's repository.

The next coding session can reuse the signal definitions after explicitly versioning the live instrument/date configuration. It must process actual arrival times, bar finalization and clock drift, preserve signal and receipt timestamps, reject stale/gapped feeds, and append immutable observations. Shadow simulated fills and broker-paper fills need separate ledgers. Deduplicate event/intent/fill IDs, reconcile cancel/fill races, restart from acknowledged positions and block new intents until reconciliation completes.

Begin with an authorized feed and a simulator without broker endpoints. Before a prospective observation starts, freeze its exact sessions and analysis plan. No elapsed forward results or automatic background monitoring are implied by this handoff. Tradovate's [retail API requirements](https://tradovate.zendesk.com/hc/en-us/articles/4408927027987-How-Do-I-Get-Access-to-the-Tradovate-API) include account and paid-access prerequisites; a demo API should not be assumed immediately available or free.

# Run manifest

```json
{
  "strategyVersion": "TJR_BC23_MNQZ25_SWEEP_BOS_v0.1",
  "frozenAtUTC": "2026-10-14 15:28:20 UTC",
  "codeHash": null,
  "parameterHash": null,
  "campaign": {
    "development": [
      "2025-09-22",
      "2025-10-31"
    ],
    "holdout": [
      "2025-11-03",
      "2025-12-12"
    ],
    "warmupFirstPriorSession": "2025-09-19",
    "holdoutOpenedBeforeFreeze": false
  },
  "rawContract": "MNQZ2025",
  "providerSymbol": null,
  "tickSize": 0.25,
  "pointValueUSD": 2,
  "researchQuantity": 1,
  "provider": null,
  "license": null,
  "dataSha256": null,
  "adjusted": false,
  "calendarReviewed": false,
  "provenanceReviewed": false,
  "holdoutOpenedBeforeFreeze": false,
  "actualFeePerSideUSD": null,
  "actualSpreadData": null,
  "historicalTradesTested": 0,
  "paperTradingStatus": "NOT_STARTED",
  "brokerExecutionEnabled": false
}
```

# Run and test

Copy the engine and test blocks into one JavaScript file in that order. Run in a modern Node.js runtime with Intl timezone support and append console.log(testReport) to display results. No dependency installation is required. Canonical bar fields are t (UTC epoch milliseconds, interval start), contract, o/h/l/c (integer ticks), and optional v. USD calculations use $0.50 per tick. The raw provider adapter and authoritative exchange-calendar mapping remain to be built.

The regression harness uses invented prices and sessions. Passing cases cover long/short symmetry, delayed entry, structural stop and target, gaps, intrabar ambiguity, exact target touches, cancellation, missing data, DST, cohort separation and unresolved-manifest guards. Passing does not establish historical returns.

Independent review found and corrected three pre-data implementation defects: opposite-boundary touches during initial sweeps, opening target priority at the time cutoff, and partial-minute session timestamps. Regression cases cover all three. Reporting also separates planned session exclusions, and exit records preserve time uncertainty. These corrections occurred before historical data access; the frozen strategy choices and cohort dates were retained.

## Engine

```js
// TJR-inspired experimental research prototype. No broker or network calls.
const V="TJR_BC23_MNQZ25_SWEEP_BOS_v0.1";
const M=60000, TICK_USD=0.50, CONTRACT="MNQZ2025";
const CFG=Object.freeze({version:V,contract:CONTRACT,entryEnd:90,flatAt:120,
  candidateLife:15,entryDelayBars:2,stopBufferTicks:1,maxCandidates:1,quantity:1});
const NY=new Intl.DateTimeFormat("en-CA",{timeZone:"America/New_York",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
function local(t){const p=Object.fromEntries(NY.formatToParts(new Date(t)).map(x=>[x.type,x.value]));return {date:p.year+"-"+p.month+"-"+p.day,minute:+p.hour*60+(+p.minute)};}
function validMinute(t){return Number.isSafeInteger(t)&&t%M===0&&Number.isFinite(new Date(t).getTime());}
function cohort(date){return date>="2025-09-22"&&date<="2025-10-31"?"DEVELOPMENT":date>="2025-11-03"&&date<="2025-12-12"?"HOLDOUT":null;}
function barError(b,t){if(!b||b.contract!==CONTRACT)return "CONTRACT_MISMATCH";
  if(b.t!==t)return "MISSING_DUPLICATE_OR_OUT_OF_ORDER_BAR";
  if(!["o","h","l","c"].every(k=>Number.isSafeInteger(b[k])&&b[k]>0))return "INVALID_TICK_PRICE";
  if(b.l>Math.min(b.o,b.c)||b.h<Math.max(b.o,b.c)||b.h<b.l)return "INVALID_OHLC";
  if(b.v!==undefined&&(!Number.isFinite(b.v)||b.v<0))return "INVALID_VOLUME";
  return null;}
function costError(c){return !c||!["SCENARIO","VERIFIED_ACCOUNT_QUOTE"].includes(c.kind)||
  !Number.isFinite(c.feePerSideUSD)||c.feePerSideUSD<0||
  !Number.isSafeInteger(c.aggressiveFrictionTicks)||c.aggressiveFrictionTicks<0?"COSTS_UNRESOLVED":null;}
function exitEvent(p,b,c){
  const d=p.d, stopOpen=d===1?b.o<=p.stop:b.o>=p.stop;
  const targetOpen=d===1?b.o>=p.target+1:b.o<=p.target-1;
  const stopHit=d===1?b.l<=p.stop:b.h>=p.stop;
  const targetHit=d===1?b.h>=p.target+1:b.l<=p.target-1;
  if(stopOpen)return {price:b.o-d*c.aggressiveFrictionTicks,reason:"STOP_GAP",ambiguous:false};
  if(targetOpen)return {price:p.target,reason:"TARGET_AT_OPEN",ambiguous:false};
  if(stopHit)return {price:p.stop-d*c.aggressiveFrictionTicks,reason:"STOP",ambiguous:targetHit};
  if(targetHit)return {price:p.target,reason:"TARGET",ambiguous:false};
  return null;
}
function simulateDay(previous,bars,meta,cost){
  const events=[],trades=[];
  const out=(status,reason)=>({version:V,status,reason,dataKind:meta?.dataKind,
    costKind:cost?.kind,cohort:meta?.date?cohort(meta.date):null,events,trades,
    netUSD:status==="COMPLETE"?trades.reduce((s,t)=>s+t.netUSD,0):null,executionEnabled:false});
  if(!meta||!["SYNTHETIC","HISTORICAL"].includes(meta.dataKind))return out("BLOCKED","DATA_KIND_REQUIRED");
  if(costError(cost))return out("BLOCKED",costError(cost));
  if(!validMinute(meta.open)||local(meta.open).minute!==570||local(meta.open).date!==meta.date)return out("BLOCKED","SESSION_CLOCK_MISMATCH");
  if(!cohort(meta.date))return out("BLOCKED","OUTSIDE_FROZEN_CAMPAIGN");
  if(meta.calendarStatus!=="REGULAR"||meta.previousCalendarStatus!=="REGULAR")return out("SKIPPED","SHORT_OR_NONTRADING_SESSION");
  if(meta.previousSessionVerified!==true||!validMinute(meta.previousOpen)||meta.previousOpen>=meta.open||
    local(meta.previousOpen).minute!==570)return out("BLOCKED","PREVIOUS_SESSION_IDENTITY_UNVERIFIED");
  if(!Array.isArray(previous)||previous.length!==390)return out("BLOCKED","PREVIOUS_SESSION_INCOMPLETE");
  for(let i=0;i<390;i++){const e=barError(previous[i],meta.previousOpen+i*M);if(e)return out("BLOCKED","PREVIOUS_"+e);}
  const PH=Math.max(...previous.map(b=>b.h)),PL=Math.min(...previous.map(b=>b.l));
  if(PH<=PL)return out("BLOCKED","DEGENERATE_REFERENCE_RANGE");
  let highs=[],lows=[],candidate=null,pending=null,position=null,attempted=false,done=false;
  const emit=(type,i,extra={})=>events.push({type,barIndex:i,barAvailableAtAssumed:meta.open+(i+1)*M,...extra});
  const cancel=(reason,i)=>{emit("CANCEL",i,{reason});candidate=null;pending=null;done=true;};
  const close=(e,b,i)=>{const grossUSD=(e.price-position.entry)*position.d*TICK_USD;
    const atOpen=["STOP_GAP","TARGET_AT_OPEN","TIME_EXIT"].includes(e.reason);
    const timing={simulatedExitTime:atOpen?b.t:null,simulatedExitInterval:atOpen?null:[b.t,b.t+M]};
    const trade={...position,...timing,exit:e.price,exitBar:i,reason:e.reason,ambiguous:!!e.ambiguous,
      grossUSD,feesUSD:2*cost.feePerSideUSD,netUSD:grossUSD-2*cost.feePerSideUSD,
      fillOrigin:"OHLC_SIMULATION"};
    trades.push(trade);emit("EXIT",i,{...e,...timing,grossUSD,netUSD:trade.netUSD});position=null;done=true;};
  if(!Array.isArray(bars))return out("BLOCKED","BARS_REQUIRED");
  for(let i=0;i<bars.length;i++){
    const b=bars[i],err=i>=390?"EXCESS_SESSION_BARS":barError(b,meta.open+i*M);
    if(err)return out("INVALID_DATA",position?"OPEN_POSITION_UNRESOLVED_"+err:err);
    if(position){
      if(i===CFG.flatAt){const opening=exitEvent(position,{...b,h:b.o,l:b.o},cost);
        close(opening||{price:b.o-position.d*cost.aggressiveFrictionTicks,reason:"TIME_EXIT"},b,i);}
      else {const e=exitEvent(position,b,cost);if(e)close(e,b,i);}
    }
    if(pending&&!done){
      const hitStop=pending.d===1?b.l<=pending.stop:b.h>=pending.stop;
      const hitTarget=pending.d===1?b.h>=pending.target:b.l<=pending.target;
      if(i<pending.due&&(hitStop||hitTarget))cancel("DELAY_BAR_INVALIDATED_SETUP",i);
      else if(i===pending.due){
        const entry=b.o+pending.d*cost.aggressiveFrictionTicks;
        if(i>=CFG.entryEnd)cancel("ENTRY_WINDOW_CLOSED",i);
        else if(!(pending.d*(b.o-pending.stop)>0&&pending.d*(entry-pending.stop)>0&&pending.d*(pending.target-entry)>0))cancel("GAP_OR_COST_INVALID_ENTRY",i);
        else {
          position={d:pending.d,entry,stop:pending.stop,target:pending.target,signalBar:pending.signalBar,entryBar:i,quantity:1};
          pending=null;emit("ENTRY",i,{...position,simulatedFillTime:b.t,fillOrigin:"OHLC_SIMULATION"});
          const e=exitEvent(position,b,cost);if(e)close(e,b,i);
        }
      }
    }
    if(candidate&&!done&&!pending&&!position){
      const age=i-candidate.sweepBar,opposite=candidate.d===1?b.h>=PH:b.l<=PL;
      candidate.extreme=candidate.d===1?Math.min(candidate.extreme,b.l):Math.max(candidate.extreme,b.h);
      if(opposite)cancel("OPPOSITE_BOUNDARY_REACHED",i);
      else if(age>CFG.candidateLife)cancel("SETUP_EXPIRED",i);
      else if(i+CFG.entryDelayBars>=CFG.entryEnd)cancel("NO_ELIGIBLE_ENTRY_TIME",i);
      else if(age>=1){
        const ref=candidate.d===1?highs.at(-1):lows.at(-1);
        if(ref!==undefined&&candidate.d*(b.c-ref)>0){
          pending={d:candidate.d,stop:candidate.extreme-candidate.d*CFG.stopBufferTicks,
            target:candidate.d===1?PH:PL,signalBar:i,due:i+CFG.entryDelayBars};
          emit("SIGNAL",i,{...pending,reference:ref});candidate=null;
        }
      }
    }
    if(!attempted&&!done&&!candidate&&!pending&&!position&&i<CFG.entryEnd){
      const below=b.l<PL,above=b.h>PH;
      if(below||above){
        attempted=true;
        const up=highs.length>=2&&lows.length>=2&&highs.at(-1)>highs.at(-2)&&lows.at(-1)>lows.at(-2);
        const down=highs.length>=2&&lows.length>=2&&highs.at(-1)<highs.at(-2)&&lows.at(-1)<lows.at(-2);
        const d=below?1:-1;
        if(below&&above)cancel("DUAL_BOUNDARY_SWEEP",i);
        else if((below&&b.h>=PH)||(above&&b.l<=PL))cancel("OPPOSITE_BOUNDARY_REACHED_ON_SWEEP",i);
        else if(!(d===1?down:up))cancel("APPROACH_TREND_NOT_ESTABLISHED",i);
        else {candidate={d,sweepBar:i,extreme:d===1?b.l:b.h};emit("SWEEP",i,{...candidate});}
      }
    }
    if(i>0){
      const a=bars[i-1],ca=Math.sign(a.c-a.o),cb=Math.sign(b.c-b.o);
      if(ca===1&&cb===-1)highs.push(Math.max(a.h,b.h));
      if(ca===-1&&cb===1)lows.push(Math.min(a.l,b.l));
    }
  }
  if(bars.length!==390)return out("INCOMPLETE",position?"OPEN_POSITION_UNRESOLVED":"SESSION_NOT_COMPLETE");
  if(position)return out("INVALID_DATA","POSITION_REMAINS_OPEN");
  return out("COMPLETE",trades.length?"SIMULATED_TRADES":"NO_TRADE");
}
function summarize(days){
  const complete=days.filter(d=>d.status==="COMPLETE"),trades=complete.flatMap(d=>d.trades);
  let equity=0,peak=0,drawdown=0,streak=0,longest=0;
  for(const d of complete){equity+=d.netUSD;peak=Math.max(peak,equity);drawdown=Math.max(drawdown,peak-equity);
    for(const t of d.trades){streak=t.netUSD<0?streak+1:0;longest=Math.max(longest,streak);}}
  const count=status=>days.filter(d=>d.status===status).length;
  return {suppliedDays:days.length,completeDays:complete.length,skippedDays:count("SKIPPED"),
    blockedDays:count("BLOCKED"),invalidDays:count("INVALID_DATA"),incompleteDays:count("INCOMPLETE"),
    unresolvedDays:days.length-complete.length-count("SKIPPED"),
    tradesOnUnresolvedDays:days.filter(d=>d.status!=="COMPLETE"&&d.status!=="SKIPPED").flatMap(d=>d.trades).length,
    noTradeDays:complete.filter(d=>!d.trades.length).length,trades:trades.length,
    grossUSD:trades.reduce((s,t)=>s+t.grossUSD,0),netUSD:equity,
    closedSessionDrawdownUSD:drawdown,longestLosingTradeRun:longest,
    ambiguousTrades:trades.filter(t=>t.ambiguous).length,
    performanceClaimAllowed:false};
}
function runCampaign(sessions,partition,cost,manifest){
  const blocked=reason=>({status:"BLOCKED",reason,historicalTradesTested:0});
  if(!["DEVELOPMENT","HOLDOUT"].includes(partition))return blocked("INVALID_PARTITION");
  if(!manifest||manifest.strategyVersion!==V||manifest.codeHash===null||!manifest.codeHash||
    !manifest.parameterHash||!manifest.frozenAtUTC||!manifest.dataSha256||
    !manifest.provider||!manifest.license||manifest.rawContract!==CONTRACT||
    manifest.adjusted!==false||manifest.calendarReviewed!==true||
    manifest.provenanceReviewed!==true)return blocked("MANIFEST_UNVERIFIED");
  if(partition==="HOLDOUT"&&manifest.holdoutOpenedBeforeFreeze!==false)return blocked("HOLDOUT_CONTAMINATION_UNKNOWN");
  if(!Array.isArray(sessions)||sessions.length===0)return blocked("NO_HISTORICAL_DATA");
  const ordered=[...sessions].sort((a,b)=>String(a.meta?.date).localeCompare(String(b.meta?.date)));
  if(new Set(ordered.map(s=>s.meta?.date)).size!==ordered.length)return blocked("DUPLICATE_SESSION");
  if(ordered.some(s=>s.meta?.dataKind!=="HISTORICAL"||cohort(s.meta.date)!==partition))return blocked("WRONG_DATA_OR_COHORT");
  if(costError(cost))return blocked(costError(cost));
  const days=ordered.map(s=>simulateDay(s.previous,s.bars,s.meta,cost));
  return {status:"SCENARIO_REPLAY",partition,manifest,cost,days,summary:summarize(days),
    note:"Caller-supplied provenance assertions require independent verification. OHLC fills are simulated."};
}
function costScenarios(){
  return [0.5,1,1.5].flatMap(feePerSideUSD=>[1,2,4].map(aggressiveFrictionTicks=>({
    kind:"SCENARIO",feePerSideUSD,aggressiveFrictionTicks,
    note:"Illustrative sensitivity assumption, not a broker quote"})));
}
```

## Synthetic checks

```js
const OPEN=Date.parse("2025-10-01T13:30:00Z"),PREV=Date.parse("2025-09-30T13:30:00Z");
const meta={dataKind:"SYNTHETIC",open:OPEN,previousOpen:PREV,date:"2025-10-01",
  calendarStatus:"REGULAR",previousCalendarStatus:"REGULAR",previousSessionVerified:true};
const cost={kind:"SCENARIO",feePerSideUSD:0.50,aggressiveFrictionTicks:1};
const B=(t,o=110,h=111,l=109,c=110)=>({t,contract:"MNQZ2025",o,h,l,c});
const previous=Array.from({length:390},(_,i)=>B(PREV+i*60000,110,120,100,110));
function setup(outcome="time"){
 const bars=Array.from({length:390},(_,i)=>B(OPEN+i*60000));
 const sequence=[[110,114,109,113],[113,113,107,108],[108,111,106,110],
 [110,111,102,103],[103,107,101,106],[106,107,98,99],
 [99,109,99,108],[108,109,106,108],[109,113,108,112]];
 sequence.forEach((v,i)=>{bars[i]=B(OPEN+i*60000,...v);});
 if(outcome==="target")bars[9]=B(OPEN+9*60000,112,121,110,120);
 if(outcome==="stop")bars[9]=B(OPEN+9*60000,110,111,96,98);
 if(outcome==="both")bars[9]=B(OPEN+9*60000,110,121,96,110);
 if(outcome==="gapstop")bars[9]=B(OPEN+9*60000,95,98,94,96);
 if(outcome==="gap_target")bars[9]=B(OPEN+9*60000,122,123,96,110);
 return bars;
}
const mirror=bars=>bars.map(b=>({...b,o:220-b.o,h:220-b.l,l:220-b.h,c:220-b.c}));
const tests=[];
function check(name,fn){let passed=false,error=null;try{passed=fn()===true;if(!passed)error="assertion";}catch(e){error=e.message;}tests.push({name,passed,error});}
const run=(bars,overrides={},c=cost)=>simulateDay(previous,bars,{...meta,...overrides},c);
const eventsOf=(r,type)=>r.events.filter(e=>e.type===type);
check("complete no-sweep session has zero trades",()=>run(Array.from({length:390},(_,i)=>B(OPEN+i*60000))).trades.length===0);
check("long structural sequence emits one trade",()=>{const r=run(setup("target"));return r.status==="COMPLETE"&&r.trades.length===1&&r.trades[0].d===1;});
check("one full minute delay before entry",()=>{const t=run(setup("target")).trades[0];return t.signalBar===6&&t.entryBar===8;});
check("stop beyond sweep extreme and opposing target",()=>{const t=run(setup("target")).trades[0];return t.stop===97&&t.target===120;});
check("long target net includes entry friction and fees",()=>run(setup("target")).netUSD===4);
check("long stop net includes both aggressive fills",()=>run(setup("stop")).netUSD===-8);
check("long gap stop uses worse opening price",()=>run(setup("gapstop")).netUSD===-9);
check("intrabar stop target conflict flagged adverse",()=>{const t=run(setup("both")).trades[0];return t.reason==="STOP"&&t.ambiguous&&t.netUSD===-8;});
check("opening target precedes later same-bar stop",()=>{const t=run(setup("gap_target")).trades[0];return t.reason==="TARGET_AT_OPEN"&&!t.ambiguous&&t.netUSD===4;});
check("short symmetry target",()=>run(mirror(setup("target"))).netUSD===4);
check("short symmetry stop",()=>run(mirror(setup("stop"))).netUSD===-8);
check("short symmetry gap stop",()=>run(mirror(setup("gapstop"))).netUSD===-9);
check("short opening target precedes later stop",()=>run(mirror(setup("gap_target"))).trades[0].reason==="TARGET_AT_OPEN");
check("fixed time exit at 11:30 is distinct from entry cutoff",()=>{const t=run(setup()).trades[0];return t.exitBar===120&&t.reason==="TIME_EXIT"&&t.netUSD===-1.5;});
check("exact target touch does not fill",()=>{const b=setup();b[9]=B(OPEN+9*60000,112,120,110,115);return run(b).trades[0].reason==="TIME_EXIT";});
check("delay-bar target touch cancels pending entry",()=>{const b=setup();b[7]=B(OPEN+7*60000,108,120,106,110);return run(b).reason==="NO_TRADE"&&eventsOf(run(b),"CANCEL")[0].reason==="DELAY_BAR_INVALIDATED_SETUP";});
check("delay-bar stop touch cancels pending entry",()=>{const b=setup();b[7]=B(OPEN+7*60000,108,109,97,108);return run(b).trades.length===0;});
check("entry gap beyond target cancels",()=>{const b=setup();b[8]=B(OPEN+8*60000,121,123,120,122);return eventsOf(run(b),"CANCEL")[0].reason==="GAP_OR_COST_INVALID_ENTRY";});
check("entry opening at stop cancels despite friction",()=>{const b=setup();b[8]=B(OPEN+8*60000,97,99,96,98);return run(b).trades.length===0;});
check("early sweep without prior trend consumes candidate",()=>{const b=setup();b[0]=B(OPEN,110,114,99,113);return eventsOf(run(b),"CANCEL")[0].reason==="APPROACH_TREND_NOT_ESTABLISHED"&&run(b).trades.length===0;});
check("dual-boundary first sweep rejected",()=>{const b=setup();b[5]=B(OPEN+5*60000,106,121,98,105);return eventsOf(run(b),"CANCEL")[0].reason==="DUAL_BOUNDARY_SWEEP";});
check("doji does not create or bridge a pair",()=>{const b=setup();b[2]=B(OPEN+2*60000,108,111,106,108);return eventsOf(run(b),"CANCEL")[0].reason==="APPROACH_TREND_NOT_ESTABLISHED";});
check("BOS equality does not confirm",()=>{const b=setup();b[6]=B(OPEN+6*60000,99,109,99,107);return !eventsOf(run(b),"SIGNAL").some(e=>e.barIndex===6);});
check("wick-only break does not confirm",()=>{const b=setup();b[6]=B(OPEN+6*60000,99,112,99,106);return !eventsOf(run(b),"SIGNAL").some(e=>e.barIndex===6);});
check("missing minute preserves open unresolved trade",()=>{const b=setup();b.splice(9,1);const r=run(b);return r.status==="INVALID_DATA"&&r.netUSD===null&&r.reason.startsWith("OPEN_POSITION_UNRESOLVED")&&eventsOf(r,"ENTRY").length===1;});
check("incomplete feed cannot report complete profit",()=>{const r=run(setup("target").slice(0,10));return r.status==="INCOMPLETE"&&r.trades.length===1&&r.netUSD===null;});
check("duplicate timestamp rejected",()=>{const b=setup();b[9]={...b[8]};return run(b).status==="INVALID_DATA";});
check("wrong contract rejected",()=>{const b=setup();b[0].contract="NQZ2025";return run(b).status==="INVALID_DATA";});
check("noninteger normalized tick prices rejected",()=>{const b=setup();b[0].c=112.5;return run(b).status==="INVALID_DATA";});
check("impossible OHLC rejected",()=>{const b=setup();b[0].h=109;return run(b).status==="INVALID_DATA";});
check("missing costs block PnL",()=>run(setup(),{},null).reason==="COSTS_UNRESOLVED");
check("negative fees rejected",()=>run(setup(),{},{...cost,feePerSideUSD:-1}).reason==="COSTS_UNRESOLVED");
check("unknown preceding session blocks",()=>run(setup(),{previousSessionVerified:false}).status==="BLOCKED");
check("shortened prior session skipped without substitution",()=>run(setup(),{previousCalendarStatus:"EARLY_CLOSE"}).status==="SKIPPED");
check("shortened current session skipped",()=>run(setup(),{calendarStatus:"EARLY_CLOSE"}).status==="SKIPPED");
check("bad New York open clock blocks",()=>run(setup(),{open:OPEN+60000}).reason==="SESSION_CLOCK_MISMATCH");
check("fall DST maps 14:30 UTC to 09:30 New York",()=>local(Date.parse("2025-11-03T14:30:00Z")).minute===570);
check("October DST maps 13:30 UTC to 09:30 New York",()=>local(OPEN).minute===570);
check("split boundaries frozen",()=>cohort("2025-10-31")==="DEVELOPMENT"&&cohort("2025-11-03")==="HOLDOUT"&&cohort("2025-12-15")===null);
check("future appended bars preserve earlier event trace",()=>{const b=setup("target");const early=run(b.slice(0,9));const full=run(b);return JSON.stringify(early.events)===JSON.stringify(full.events.filter(e=>e.barIndex<9));});
check("input not mutated and replay deterministic",()=>{const b=setup("target"),before=JSON.stringify(b);const a=run(b),c=run(b);return JSON.stringify(b)===before&&JSON.stringify(a)===JSON.stringify(c);});
check("all scenarios charge higher fees monotonically",()=>run(setup("target"),{},{...cost,feePerSideUSD:1}).netUSD===3);
check("summary keeps unresolved day denominator",()=>{const r=summarize([run(setup("target")),run(setup("stop")),run(setup().slice(0,9))]);return r.suppliedDays===3&&r.completeDays===2&&r.unresolvedDays===1&&r.netUSD===-4&&r.performanceClaimAllowed===false;});
check("historical run rejects missing manifest",()=>runCampaign([],"HOLDOUT",cost,null).reason==="MANIFEST_UNVERIFIED");
const fakeManifest={strategyVersion:V,codeHash:"synthetic-fixture",parameterHash:"synthetic-fixture",
 frozenAtUTC:"2026-10-14T15:25:44Z",dataSha256:"synthetic-fixture",provider:"TEST_ONLY",license:"TEST_ONLY",
 rawContract:CONTRACT,adjusted:false,calendarReviewed:true,provenanceReviewed:true,holdoutOpenedBeforeFreeze:false};
check("empty historical dataset remains untested",()=>runCampaign([],"DEVELOPMENT",cost,fakeManifest).reason==="NO_HISTORICAL_DATA");
check("synthetic input cannot enter historical report",()=>runCampaign([{previous,bars:setup(),meta}],"DEVELOPMENT",cost,fakeManifest).reason==="WRONG_DATA_OR_COHORT");
check("unknown holdout exposure blocks",()=>runCampaign([],"HOLDOUT",cost,{...fakeManifest,holdoutOpenedBeforeFreeze:null}).reason==="HOLDOUT_CONTAMINATION_UNKNOWN");
check("adjusted data manifest blocks",()=>runCampaign([],"DEVELOPMENT",cost,{...fakeManifest,adjusted:true}).reason==="MANIFEST_UNVERIFIED");
check("cost grid exposes all nine assumptions",()=>costScenarios().length===9&&costScenarios().every(c=>c.kind==="SCENARIO"));
check("target at time-exit open retains resting limit price",()=>{const b=setup();b[120]=B(OPEN+120*60000,122,123,121,122);const r=run(b);return r.trades[0].reason==="TARGET_AT_OPEN"&&r.trades[0].exit===120&&r.netUSD===4;});
check("short target at cutoff retains limit price",()=>{const b=setup();b[120]=B(OPEN+120*60000,122,123,121,122);const r=run(mirror(b));return r.trades[0].reason==="TARGET_AT_OPEN"&&r.netUSD===4;});
check("stop gap at cutoff keeps opening adverse fill",()=>{const b=setup();b[120]=B(OPEN+120*60000,95,98,94,96);return run(b).trades[0].reason==="STOP_GAP"&&run(b).netUSD===-9;});
check("time exit cannot use later intrabar target",()=>{const b=setup();b[120]=B(OPEN+120*60000,110,122,100,115);return run(b).trades[0].reason==="TIME_EXIT"&&run(b).netUSD===-1.5;});
check("30-second shifted session timestamps rejected",()=>{const p=previous.map(b=>({...b,t:b.t+30000})),b=setup().map(b=>({...b,t:b.t+30000}));return simulateDay(p,b,{...meta,open:OPEN+30000,previousOpen:PREV+30000},cost).reason==="SESSION_CLOCK_MISMATCH";});
check("misaligned preceding session rejected",()=>simulateDay(previous.map(b=>({...b,t:b.t+30000})),setup(),{...meta,previousOpen:PREV+30000},cost).reason==="PREVIOUS_SESSION_IDENTITY_UNVERIFIED");
check("opposite-boundary exact touch on sweep cancels",()=>{const b=setup();b[5]=B(OPEN+5*60000,106,120,98,108);b[6]=B(OPEN+6*60000,108,110,105,109);const r=run(b);return r.trades.length===0&&eventsOf(r,"CANCEL")[0].reason==="OPPOSITE_BOUNDARY_REACHED_ON_SWEEP";});
check("short sweep opposite exact touch cancels",()=>{const b=setup();b[5]=B(OPEN+5*60000,106,120,98,108);return run(mirror(b)).trades.length===0;});
function delayedConfirmation(age){const b=setup();for(let i=6;i<390;i++)b[i]=B(OPEN+i*60000,99,106,99,99);const k=5+age;b[k]=B(OPEN+k*60000,99,109,99,108);b[k+1]=B(OPEN+(k+1)*60000,108,109,106,108);b[k+2]=B(OPEN+(k+2)*60000,109,113,108,112);for(let i=k+3;i<390;i++)b[i]=B(OPEN+i*60000);return b;}
check("15th subsequent candle remains eligible",()=>run(delayedConfirmation(15)).trades.length===1);
check("16th subsequent candle expires",()=>{const r=run(delayedConfirmation(16));return r.trades.length===0&&eventsOf(r,"CANCEL")[0].reason==="SETUP_EXPIRED";});
function shiftedSetup(shift){const orig=setup("target"),b=Array.from({length:390},(_,i)=>B(OPEN+i*60000));for(let i=0;i<10;i++)b[shift+i]={...orig[i],t:OPEN+(shift+i)*60000};return b;}
check("entry at 10:58 remains allowed",()=>run(shiftedSetup(80)).trades[0].entryBar===88);
check("entry at 11:00 is blocked",()=>run(shiftedSetup(82)).trades.length===0);
check("opening exit records simulated timestamp",()=>{const x=run(setup("gap_target")).trades[0];return x.simulatedExitTime===OPEN+9*60000&&x.simulatedExitInterval===null;});
check("intrabar exit preserves uncertain time interval",()=>{const x=run(setup("stop")).trades[0];return x.simulatedExitTime===null&&x.simulatedExitInterval[0]===OPEN+9*60000&&x.simulatedExitInterval[1]===OPEN+10*60000;});
check("calendar exclusions are distinct from unresolved data",()=>{const r=summarize([run(setup(),{calendarStatus:"EARLY_CLOSE"}),run(setup().slice(0,9))]);return r.suppliedDays===2&&r.skippedDays===1&&r.incompleteDays===1&&r.unresolvedDays===1;});
check("closed trades on incomplete days remain counted separately",()=>{const r=summarize([run(setup("target").slice(0,10))]);return r.tradesOnUnresolvedDays===1&&r.trades===0&&r.netUSD===0;});
const testReport={scope:"SYNTHETIC ONLY: no historical market data",passed:tests.filter(t=>t.passed).length,total:tests.length,failures:tests.filter(t=>!t.passed),tests};
if(testReport.failures.length)throw Error(JSON.stringify(testReport.failures));
```
