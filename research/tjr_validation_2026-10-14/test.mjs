/** Invented data only: these assertions are not historical evidence. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {spawnSync} from 'node:child_process';
import {HERE, loadEngine, loadSources, engineContext, reproduceOriginalChecks, sha256} from './sources.mjs';
import {PROTOCOL, dates, validateCalendar, validateMapping, validateBars, readBundle, evaluateBundle} from './run.mjs';
const cases=[];
function check(name,fn){try{fn();cases.push({name,passed:true});}catch(error){cases.push({name,passed:false,error:error.message});}}
const clone=x=>structuredClone(x);
const {api,source}=loadEngine();
const ctx=engineContext(source.engine+'\n'+source.originalTests);
const fixtures=vm.runInContext('({meta,cost,previous,setup})',ctx);
const synthetic=overrides=>api.simulateDay(fixtures.previous,fixtures.setup('target'),{...fixtures.meta,...overrides},fixtures.cost);
check('saved prototype original 65 checks pass unchanged',()=>assert.equal(reproduceOriginalChecks().prototype.passed,65));
check('saved feature original 26 checks pass unchanged',()=>assert.equal(reproduceOriginalChecks().feature.passed,26));
check('calendar derivative preserves all original 65 checks',()=>assert.equal(reproduceOriginalChecks().derivativeCompatibility.passed,65));
for(const field of ['calendarStatus','previousCalendarStatus'])for(const value of [undefined,null,'UNVERIFIED','TYPO']) {
  check(`${field}=${String(value)} remains unresolved`,()=>{
    const r=synthetic({[field]:value});assert.equal(r.status,'BLOCKED');assert.equal(r.reason,'CALENDAR_UNVERIFIED');
    assert.equal(r.netUSD,null);assert.equal(api.summarize([r]).unresolvedDays,1);assert.equal(api.summarize([r]).skippedDays,0);
  });
}
check('unknown prior remains unresolved even if current explicitly excluded',()=>assert.equal(synthetic({calendarStatus:'EARLY_CLOSE',previousCalendarStatus:undefined}).status,'BLOCKED'));
check('verified closure is a planned exclusion',()=>assert.equal(synthetic({calendarStatus:'CLOSED'}).status,'SKIPPED'));
check('versioned patch changes only version and calendar check',()=>{
  const revised=source.engine.replace('v0.1.1_calendar','v0.1').replace(
    '  const calendarStatuses=["REGULAR","EARLY_CLOSE","CLOSED"];\n  if(!calendarStatuses.includes(meta.calendarStatus)||!calendarStatuses.includes(meta.previousCalendarStatus))return out("BLOCKED","CALENDAR_UNVERIFIED");\n','');
  assert.equal(revised,source.originalEngine);
});
check('engine VM has no network, process, module loader or broker',()=>{
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify([typeof fetch,typeof process,typeof require,typeof WebSocket,typeof broker])',ctx)),Array(5).fill('undefined'));
  assert.equal(synthetic({}).executionEnabled,false);
});
const calendar={timezone:'America/New_York',reviewed:true,sources:[{id:'SYNTHETIC_TEST_ONLY',url:'https://example.invalid/test',description:'Invented fixture, never a real calendar'}],rows:[]};
let previous=null;
for(const date of dates(PROTOCOL.warmup,PROTOCOL.end)){
  const weekday=new Date(date+'T12:00:00Z').getUTCDay(),closed=[0,6].includes(weekday);
  calendar.rows.push({date,status:closed?'CLOSED':'REGULAR',openUtc:closed?null:date+'T13:30:00Z',previousSessionDate:closed?null:previous,sourceRef:'SYNTHETIC_TEST_ONLY'});
  if(!closed)previous=date;
}
const mapped=validateCalendar(calendar,api);
check('all 43 civil dates and 31 cash sessions incl warmup retained',()=>{assert.equal(mapped.size,43);assert.equal(calendar.rows.filter(r=>r.status==='REGULAR').length,31);});
check('calendar omission cannot vanish from denominator',()=>{const c=clone(calendar);c.rows.splice(5,1);assert.throws(()=>validateCalendar(c,api),/CALENDAR_DATE_MISSING/);});
check('duplicate calendar dates rejected',()=>{const c=clone(calendar);c.rows.push(c.rows[0]);assert.throws(()=>validateCalendar(c,api),/DUPLICATE_CALENDAR_DATE/);});
check('calendar outside frozen period rejected',()=>{const c=clone(calendar);c.rows.push({...c.rows[0],date:'2025-11-03'});assert.throws(()=>validateCalendar(c,api),/CALENDAR_DATE_OUTSIDE/);});
check('calendar status unknown rejected',()=>{const c=clone(calendar);c.rows[3].status='UNKNOWN';assert.throws(()=>validateCalendar(c,api),/CALENDAR_UNVERIFIED/);});
check('calendar source per date required',()=>{const c=clone(calendar);c.rows[3].sourceRef='unknown';assert.throws(()=>validateCalendar(c,api),/CALENDAR_ROW_SOURCE/);});
check('preceding session cannot silently substitute an earlier day',()=>{const c=clone(calendar);c.rows[4].previousSessionDate='2025-09-19';assert.throws(()=>validateCalendar(c,api),/PREVIOUS_SESSION_LINK/);});
check('clock must be cash open in New York',()=>{const c=clone(calendar);c.rows[3].openUtc='2025-09-22T14:30:00Z';assert.throws(()=>validateCalendar(c,api),/CALENDAR_OPEN_MISMATCH/);});
check('partial-minute cash open rejected',()=>{const c=clone(calendar);c.rows[3].openUtc='2025-09-22T13:30:30Z';assert.throws(()=>validateCalendar(c,api),/CALENDAR_OPEN_MISMATCH/);});
check('weekend cannot be promoted to regular session',()=>{const c=clone(calendar);c.rows[1].status='REGULAR';assert.throws(()=>validateCalendar(c,api),/WEEKEND_SESSION/);});
const mapping={canonicalContract:'MNQZ2025',providerSymbol:'MNQZ5',exchange:'CME',expirationMonth:'2025-12',instrumentType:'FUTURE',minPriceIncrement:0.25,pointValueUSD:2,adjusted:false,sourceEvidence:'SYNTHETIC_TEST_ONLY'};
check('actual contract mapping accepts matching test evidence',()=>validateMapping(mapping,{providerSymbol:'MNQZ5'}));
for(const [key,value] of [['canonicalContract','NQZ2025'],['expirationMonth','2026-06'],['minPriceIncrement',1],['adjusted',true],['pointValueUSD',20],['providerSymbol','MNQ.c.0']])
  check('contract mapping rejects '+key,()=>assert.throws(()=>validateMapping({...mapping,[key]:value},{providerSymbol:'MNQZ5'}),/ACTUAL_CONTRACT_MAPPING/));
const bar=(date,i=0)=>({t:Date.parse(date+'T13:30:00Z')+i*60000,contract:'MNQZ2025',o:110,h:120,l:100,c:110});
check('bars never shift or fill missing minutes',()=>assert.equal(validateBars([bar('2025-09-19',0),bar('2025-09-19',2)],mapped,api).get('2025-09-19').length,2));
for(const [name,bars,reason]of [
  ['duplicate',[bar('2025-09-19'),bar('2025-09-19')],'DUPLICATE_BAR'],
  ['out of order',[bar('2025-09-19',1),bar('2025-09-19',0)],'OUT_OF_ORDER_BAR'],
  ['wrong instrument',[{...bar('2025-09-19'),contract:'NQZ2025'}],'CONTRACT_MISMATCH'],
  ['wrong precision',[{...bar('2025-09-19'),o:110.5}],'INVALID_TICK_PRICE'],
  ['malformed OHLC',[{...bar('2025-09-19'),l:111}],'INVALID_OHLC'],
  ['negative volume',[{...bar('2025-09-19'),v:-1}],'INVALID_VOLUME'],
  ['overnight',[bar('2025-09-19',-1)],'BAR_OUTSIDE_CASH_SESSION'],
  ['closed session',[bar('2025-09-20')],'BAR_ON_CLOSED'],
  ['holdout',[{...bar('2025-11-03'),t:Date.parse('2025-11-03T14:30:00Z')}],'NON_DEVELOPMENT_BAR'],
])check(name+' bars rejected',()=>assert.throws(()=>validateBars(bars,mapped,api),new RegExp(reason)));
const bars=calendar.rows.filter(r=>r.status==='REGULAR').flatMap(r=>Array.from({length:390},(_,i)=>bar(r.date,i)));
const manifest={schemaVersion:1,dataKind:'HISTORICAL',partition:'DEVELOPMENT',canonicalContract:'MNQZ2025',provider:'SYNTHETIC_TEST_ONLY',providerSymbol:'MNQZ5',license:'TEST_ONLY',adjusted:false,priceUnit:'INTEGER_TICKS',timestampConvention:'UTC_INTERVAL_START',tickSize:0.25,review:{provenanceVerified:true,mappingVerified:true,calendarVerified:true,reviewedBy:'TEST_ONLY',reviewedAtUTC:'2026-10-14T18:00:00Z',evidenceNotes:'Fabricated test fixture, not historical evidence'},bars:{sha256:'a'.repeat(64)}};
const bundle={manifest,manifestSha256:'b'.repeat(64),calendar,bars,actualAccountCosts:{status:'UNVERIFIED',actualProfitabilityEvaluated:false}};
check('full calendar creates 30 development session denominators per scenario',()=>{
  const r=evaluateBundle(bundle);assert.equal(r.expectedDevelopmentSessions,30);assert.equal(r.scenarios.length,9);
  for(const s of r.scenarios){assert.equal(s.summary.suppliedDays,30);assert.equal(s.summary.completeDays,30);assert.equal(s.summary.noTradeDays,30);}
  assert.equal(r.liveExecutionEnabled,false);assert.equal(r.paperTradingStarted,false);assert.equal(r.holdoutOpened,false);
});
check('missing complete session retains day and invalidates whole-campaign total',()=>{
  const r=evaluateBundle({...bundle,bars:bars.filter(b=>api.local(b.t).date!=='2025-10-01')});
  const s=r.scenarios[0].summary;assert.equal(s.suppliedDays,30);assert.equal(s.unresolvedDays,2);assert.equal(s.wholeCampaignNetUSD,null);
  assert.deepEqual(s.unresolvedDates.map(x=>x.date),['2025-10-01','2025-10-02']);
});
check('missing warmup blocks first development session',()=>{
  const r=evaluateBundle({...bundle,bars:bars.filter(b=>api.local(b.t).date!=='2025-09-19')});
  assert.equal(r.scenarios[0].days[0].reason,'PREVIOUS_SESSION_INCOMPLETE');assert.equal(r.scenarios[0].summary.unresolvedDays,1);
});
check('shortened prior session is excluded, never replaced',()=>{
  const c=clone(calendar);c.rows.find(x=>x.date==='2025-10-01').status='EARLY_CLOSE';
  const r=evaluateBundle({...bundle,calendar:c});assert.equal(r.scenarios[0].summary.skippedDays,2);
});
check('unresolved days retain closed losing trades without treating as full coverage',()=>{
  const b=bars.filter(b=>api.local(b.t).date!=='2025-10-01');
  b.push(...JSON.parse(JSON.stringify(fixtures.setup('stop'))).slice(0,10));b.sort((a,b)=>a.t-b.t);
  const r=evaluateBundle({...bundle,bars:b}),d=r.scenarios[0].days.find(d=>d.date==='2025-10-01');
  assert.equal(d.status,'INCOMPLETE');assert.equal(d.netUSD,null);assert.equal(d.trades[0].netUSD,-8);
  assert.equal(r.scenarios[0].summary.tradesOnUnresolvedDays,1);
  assert.equal(r.scenarios[0].summary.knownClosedTradesOnUnresolvedDaysNetUSD,-8);
  assert.equal(r.scenarios[0].summary.knownClosedTradesOnUnresolvedDaysFeesUSD,1);
  assert.equal(r.scenarios[0].summary.completeSessionNetUSD,0);
  assert.equal(r.scenarios[0].summary.knownAllClosedTradesNetUSD,-8);
  assert.equal(r.scenarios[0].summary.wholeCampaignNetUSD,null);
});
check('nine scenarios preserve losing session and adverse friction',()=>{
  const b=bars.filter(b=>api.local(b.t).date!=='2025-10-01');b.push(...JSON.parse(JSON.stringify(fixtures.setup('stop'))));b.sort((a,b)=>a.t-b.t);
  const r=evaluateBundle({...bundle,bars:b});
  for(const s of r.scenarios){const d=s.days.find(d=>d.date==='2025-10-01');assert.equal(d.trades.length,1);assert.ok(d.netUSD<0);assert.equal(d.trades[0].feesUSD,2*s.cost.feePerSideUSD);}
  assert.equal(r.scenarios[0].days.find(d=>d.date==='2025-10-01').netUSD,-8);
});
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'tjr-fixtures-'));
function artifact(name,text){fs.writeFileSync(path.join(tmp,name),text);return{path:name,sha256:sha256(Buffer.from(text))};}
const valid={...manifest,rawArtifacts:[{...artifact('raw.txt','SYNTHETIC_TEST_ONLY_NO_REAL_MARKET_DATA'),firstDate:'2025-09-19',lastDate:'2025-10-31'}],mapping:artifact('mapping.json',JSON.stringify(mapping)),calendar:artifact('calendar.json',JSON.stringify(calendar)),bars:artifact('bars.jsonl',bars.map(b=>JSON.stringify(b)).join('\n')+'\n')};
function writeManifest(m){fs.writeFileSync(path.join(tmp,'manifest.json'),JSON.stringify(m));return path.join(tmp,'manifest.json');}
check('valid hash chain can load test bundle',()=>assert.equal(readBundle(writeManifest(valid)).bars.length,12090));
check('wrong artifact hash blocks',()=>assert.throws(()=>readBundle(writeManifest({...valid,bars:{...valid.bars,sha256:'0'.repeat(64)}})),/ARTIFACT_HASH_MISMATCH/));
check('unverified mapping flags cannot run',()=>assert.throws(()=>readBundle(writeManifest({...valid,review:{...valid.review,mappingVerified:false}})),/MANIFEST_UNVERIFIED/));
check('raw provenance cannot be absent',()=>assert.throws(()=>readBundle(writeManifest({...valid,rawArtifacts:[]})),/RAW_PROVENANCE_REQUIRED/));
check('raw holdout range rejected before reading artifact',()=>assert.throws(()=>readBundle(writeManifest({...valid,rawArtifacts:[{...valid.rawArtifacts[0],path:'missing-would-not-be-read',lastDate:'2025-11-03'}]})),/RAW_ARTIFACT_RANGE/));
check('holdout partition rejected before bars read',()=>assert.throws(()=>readBundle(writeManifest({...valid,partition:'HOLDOUT',bars:{path:'missing',sha256:'0'.repeat(64)}})),/MANIFEST_UNVERIFIED/));
check('actual cost assertions need hashed evidence',()=>assert.throws(()=>readBundle(writeManifest({...valid,actualAccountCosts:{status:'VERIFIED',feePerSideUSD:1,fixedMonthlyUSD:0}})),/ARTIFACT_REFERENCE/));
check('CLI missing dataset explicitly blocked with no PnL',()=>{
  const r=spawnSync(process.execPath,[path.join(HERE,'run.mjs')],{encoding:'utf8'}),v=JSON.parse(r.stdout);
  assert.equal(r.status,2);assert.equal(v.status,'BLOCKED');assert.equal(v.historicalPnlUSD,null);assert.equal(v.historicalTradesTested,0);assert.equal(v.liveExecutionEnabled,false);
});
check('rejected supplied bundle does not claim holdout was unopened',()=>{
  const p=writeManifest({...valid,partition:'HOLDOUT'});
  const r=spawnSync(process.execPath,[path.join(HERE,'run.mjs'),'--bundle',p],{encoding:'utf8'}),v=JSON.parse(r.stdout);
  assert.equal(r.status,2);assert.equal(v.holdoutOpened,null);assert.equal(v.holdoutExposureStatus,'UNVERIFIED_INPUT_REJECTED');assert.equal(v.holdoutReplayed,false);
});
check('output cannot overwrite a previous receipt',()=>{
  const target=path.join(tmp,'keep.json');fs.writeFileSync(target,'KEEP');
  const r=spawnSync(process.execPath,[path.join(HERE,'run.mjs'),'--output',target],{encoding:'utf8'});
  assert.notEqual(r.status,0);assert.equal(fs.readFileSync(target,'utf8'),'KEEP');
});
fs.rmSync(tmp,{recursive:true,force:true});
const report={scope:'SYNTHETIC REGRESSIONS ONLY; no historical bars or returns',generatedAtUTC:new Date().toISOString(),runtime:process.version,
  passed:cases.filter(t=>t.passed).length,total:cases.length,failures:cases.filter(t=>!t.passed),tests:cases,
  sourceHashes:loadSources().hashes,historicalTradesTested:0,paperTradingStarted:false,liveExecutionEnabled:false};
process.stdout.write(JSON.stringify(report,null,2)+'\n');
if(report.failures.length)process.exitCode=1;
