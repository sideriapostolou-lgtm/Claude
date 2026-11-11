/** Offline development replay only. No feed, broker, account, or execution endpoint. */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {VERSION, sha256, loadEngine} from './sources.mjs';

export const PROTOCOL = Object.freeze({version: 'TJR_DEVELOPMENT_RUNNER_v1',
  sourceVersion: VERSION, contract: 'MNQZ2025', warmup: '2025-09-19',
  start: '2025-09-22', end: '2025-10-31', partition: 'DEVELOPMENT',
  holdout: ['2025-11-03', '2025-12-12'], liveExecutionEnabled: false,
  priceUnit: 'INTEGER_TICKS', tickSize: 0.25, tickUSD: 0.5,
  assumedBarAvailability: 'INTERVAL_CLOSE', observedLatency: false});
const DAY = 86400000, MINUTE = 60000;
const JSON_LIMIT = 64 * 1024 * 1024;
export class InputError extends Error {}
const fail = reason => { throw new InputError(reason); };
const meaningful = s => typeof s === 'string' && s.trim().length > 0;
const digest = s => typeof s === 'string' && /^[a-f0-9]{64}$/.test(s);
export function dates(start, end) {
  const result = [];
  for (let t = Date.parse(start + 'T00:00:00Z'); t <= Date.parse(end + 'T00:00:00Z'); t += DAY)
    result.push(new Date(t).toISOString().slice(0, 10));
  return result;
}
function readFile(file) {
  if (fs.statSync(file).size > JSON_LIMIT) fail('INPUT_TOO_LARGE');
  return fs.readFileSync(file);
}
function json(raw, label) {
  try { return JSON.parse(raw.toString('utf8')); } catch { fail('INVALID_JSON:' + label); }
}
function readArtifact(base, ref, label) {
  if (!ref || !meaningful(ref.path) || !digest(ref.sha256)) fail('ARTIFACT_REFERENCE_UNVERIFIED:' + label);
  const raw = readFile(path.resolve(base, ref.path));
  if (sha256(raw) !== ref.sha256) fail('ARTIFACT_HASH_MISMATCH:' + label);
  return raw;
}
export function validateCalendar(calendar, api) {
  if (!calendar || calendar.timezone !== 'America/New_York' || calendar.reviewed !== true ||
      !Array.isArray(calendar.sources) || !calendar.sources.length ||
      calendar.sources.some(x => !meaningful(x.id) || !meaningful(x.url) || !meaningful(x.description)))
    fail('CALENDAR_PROVENANCE_UNVERIFIED');
  const sourceIDs = new Set(calendar.sources.map(x => x.id));
  if (sourceIDs.size !== calendar.sources.length) fail('DUPLICATE_CALENDAR_SOURCE');
  if (!Array.isArray(calendar.rows)) fail('CALENDAR_ROWS_MISSING');
  const expected = dates(PROTOCOL.warmup, PROTOCOL.end), byDate = new Map();
  for (const row of calendar.rows) {
    if (!row || !expected.includes(row.date)) fail('CALENDAR_DATE_OUTSIDE_DEVELOPMENT');
    if (byDate.has(row.date)) fail('DUPLICATE_CALENDAR_DATE');
    if (!['REGULAR', 'EARLY_CLOSE', 'CLOSED'].includes(row.status)) fail('CALENDAR_UNVERIFIED');
    if (!sourceIDs.has(row.sourceRef)) fail('CALENDAR_ROW_SOURCE_UNVERIFIED');
    const weekday = new Date(row.date + 'T12:00:00Z').getUTCDay();
    if ((weekday === 0 || weekday === 6) && row.status !== 'CLOSED') fail('WEEKEND_SESSION_UNVERIFIED');
    if (row.status === 'CLOSED') {
      if (row.openUtc !== null) fail('CLOSED_SESSION_HAS_OPEN');
    } else {
      if (!meaningful(row.openUtc) || !row.openUtc.endsWith('Z')) fail('CALENDAR_OPEN_NOT_UTC');
      const t = Date.parse(row.openUtc), local = api.local(t);
      if (!Number.isSafeInteger(t) || t % MINUTE || local.date !== row.date || local.minute !== 570)
        fail('CALENDAR_OPEN_MISMATCH');
    }
    byDate.set(row.date, row);
  }
  if (expected.some(d => !byDate.has(d))) fail('CALENDAR_DATE_MISSING');
  let prior = null;
  for (const date of expected) {
    const row = byDate.get(date);
    if (row.status === 'CLOSED') continue;
    if (date !== PROTOCOL.warmup && row.previousSessionDate !== prior) fail('PREVIOUS_SESSION_LINK_MISMATCH');
    prior = date;
  }
  if (byDate.get(PROTOCOL.warmup).status !== 'REGULAR') fail('WARMUP_SESSION_UNVERIFIED');
  return byDate;
}
export function validateMapping(mapping, manifest) {
  if (!mapping || mapping.canonicalContract !== PROTOCOL.contract ||
      mapping.providerSymbol !== manifest.providerSymbol || mapping.exchange !== 'CME' ||
      mapping.expirationMonth !== '2025-12' || mapping.instrumentType !== 'FUTURE' ||
      mapping.minPriceIncrement !== 0.25 || mapping.pointValueUSD !== 2 ||
      mapping.adjusted !== false || !meaningful(mapping.sourceEvidence))
    fail('ACTUAL_CONTRACT_MAPPING_UNVERIFIED');
}
export function validateBars(bars, calendar, api) {
  if (!Array.isArray(bars)) fail('BARS_REQUIRED');
  const grouped = new Map(), stamps = new Set();
  let priorTime = -Infinity;
  for (const b of bars) {
    if (!b || b.contract !== PROTOCOL.contract) fail('CONTRACT_MISMATCH');
    if (!Number.isSafeInteger(b.t) || b.t % MINUTE) fail('INVALID_BAR_TIMESTAMP');
    const local = api.local(b.t);
    if (local.date < PROTOCOL.warmup || local.date > PROTOCOL.end)
      fail('NON_DEVELOPMENT_BAR_REJECTED_NOT_REPLAYED');
    if (stamps.has(b.t)) fail('DUPLICATE_BAR');
    if (b.t <= priorTime) fail('OUT_OF_ORDER_BAR');
    stamps.add(b.t); priorTime = b.t;
    const day = calendar.get(local.date);
    if (!day || day.status === 'CLOSED') fail('BAR_ON_CLOSED_OR_UNVERIFIED_SESSION');
    if (local.minute < 570 || local.minute >= 960) fail('BAR_OUTSIDE_CASH_SESSION');
    if (!['o', 'h', 'l', 'c'].every(k => Number.isSafeInteger(b[k]) && b[k] > 0)) fail('INVALID_TICK_PRICE');
    if (b.l > Math.min(b.o, b.c) || b.h < Math.max(b.o, b.c) || b.h < b.l) fail('INVALID_OHLC');
    if (b.v !== undefined && (!Number.isFinite(b.v) || b.v < 0)) fail('INVALID_VOLUME');
    if (!grouped.has(local.date)) grouped.set(local.date, []);
    grouped.get(local.date).push(b);
  }
  return grouped;
}
function costEvidence(manifest, base) {
  const cost = manifest.actualAccountCosts;
  if (!cost || cost.status !== 'VERIFIED') return {status: 'UNVERIFIED', actualProfitabilityEvaluated: false};
  readArtifact(base, cost.evidence, 'ACTUAL_COST_EVIDENCE');
  if (!Number.isFinite(cost.feePerSideUSD) || cost.feePerSideUSD < 0 ||
      !Number.isFinite(cost.fixedMonthlyUSD) || cost.fixedMonthlyUSD < 0 ||
      !meaningful(cost.accountFeeDescription)) fail('ACTUAL_COST_EVIDENCE_INCOMPLETE');
  return {...cost, actualProfitabilityEvaluated: false,
    note: 'Evidence retained; execution still uses nine frozen friction assumptions, not observed bid/ask fills.'};
}
export function readBundle(manifestPath) {
  const raw = readFile(manifestPath), manifest = json(raw, 'MANIFEST'), base = path.dirname(manifestPath);
  if (manifest.schemaVersion !== 1 || manifest.dataKind !== 'HISTORICAL' ||
      manifest.partition !== 'DEVELOPMENT' || manifest.canonicalContract !== PROTOCOL.contract ||
      manifest.adjusted !== false || manifest.priceUnit !== 'INTEGER_TICKS' ||
      manifest.timestampConvention !== 'UTC_INTERVAL_START' || manifest.tickSize !== 0.25 ||
      !meaningful(manifest.provider) || !meaningful(manifest.providerSymbol) || !meaningful(manifest.license) ||
      manifest.review?.provenanceVerified !== true || manifest.review?.mappingVerified !== true ||
      manifest.review?.calendarVerified !== true || !meaningful(manifest.review?.reviewedBy) ||
      !meaningful(manifest.review?.reviewedAtUTC) || !meaningful(manifest.review?.evidenceNotes))
    fail('MANIFEST_UNVERIFIED');
  if (!Array.isArray(manifest.rawArtifacts) || !manifest.rawArtifacts.length) fail('RAW_PROVENANCE_REQUIRED');
  for (const ref of manifest.rawArtifacts) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(ref.firstDate || '') ||
        !/^\d{4}-\d{2}-\d{2}$/.test(ref.lastDate || '') ||
        ref.firstDate < PROTOCOL.warmup || ref.lastDate > PROTOCOL.end || ref.firstDate > ref.lastDate)
      fail('RAW_ARTIFACT_RANGE_NOT_DEVELOPMENT');
    readArtifact(base, ref, 'RAW_SOURCE');
  }
  const mapping = json(readArtifact(base, manifest.mapping, 'MAPPING'), 'MAPPING');
  validateMapping(mapping, manifest);
  const calendar = json(readArtifact(base, manifest.calendar, 'CALENDAR'), 'CALENDAR');
  const barsRaw = readArtifact(base, manifest.bars, 'BARS');
  const bars = barsRaw.toString('utf8').split(/\r?\n/).filter(line => line.trim()).map(line => json(Buffer.from(line), 'BAR'));
  return {manifest, manifestSha256: sha256(raw), calendar, bars, actualAccountCosts: costEvidence(manifest, base)};
}
function enrich(result) {
  const complete = result.days.filter(d => d.status === 'COMPLETE');
  const trades = complete.flatMap(d => d.trades);
  const wins = trades.filter(t => t.netUSD > 0), losses = trades.filter(t => t.netUSD < 0);
  const positive = complete.filter(d => d.netUSD > 0).map(d => d.netUSD).sort((a,b) => b-a);
  const gains = wins.reduce((s,t) => s+t.netUSD,0), lost = -losses.reduce((s,t) => s+t.netUSD,0);
  const unresolved = result.days.filter(d => !['COMPLETE','SKIPPED'].includes(d.status));
  const knownUnresolvedTrades = unresolved.flatMap(d => d.trades);
  return {...result.summary,
    completeSessionGrossUSD: result.summary.grossUSD, completeSessionNetUSD: result.summary.netUSD,
    completeSessionFeesUSD: trades.reduce((s,t) => s+t.feesUSD,0),
    feesUSD: trades.reduce((s,t) => s+t.feesUSD,0),
    winningTrades: wins.length, losingTrades: losses.length, flatTrades: trades.length-wins.length-losses.length,
    winRate: trades.length ? wins.length/trades.length : null,
    profitFactor: lost > 0 ? gains/lost : null,
    worstCompleteSessionUSD: complete.length ? Math.min(...complete.map(d=>d.netUSD)) : null,
    bestCompleteSessionUSD: complete.length ? Math.max(...complete.map(d=>d.netUSD)) : null,
    bestSessionShareOfPositiveSessionPnl: positive.length ? positive[0]/positive.reduce((s,n)=>s+n,0) : null,
    rejectedCandidates: result.days.reduce((n,d)=>n+d.events.filter(e=>e.type==='CANCEL').length,0),
    knownClosedTradesOnUnresolvedDaysGrossUSD: knownUnresolvedTrades.reduce((n,t)=>n+t.grossUSD,0),
    knownClosedTradesOnUnresolvedDaysFeesUSD: knownUnresolvedTrades.reduce((n,t)=>n+t.feesUSD,0),
    knownClosedTradesOnUnresolvedDaysNetUSD: knownUnresolvedTrades.reduce((n,t)=>n+t.netUSD,0),
    knownAllClosedTradesNetUSD: result.summary.netUSD + knownUnresolvedTrades.reduce((n,t)=>n+t.netUSD,0),
    unresolvedPnlNote: 'Known closed trades are retained; open/missing outcomes remain unknown. Complete-session net is not the whole-campaign total.',
    unresolvedDates: unresolved.map(d=>({date:d.date,status:d.status,reason:d.reason})),
    aggregateCoverage: unresolved.length ? 'INCOMPLETE_COMPLETE_SESSIONS_ONLY' : 'ALL_SCHEDULED_DATES_CLASSIFIED',
    wholeCampaignNetUSD: unresolved.length ? null : result.summary.netUSD,
    performanceClaimAllowed: false};
}
export function evaluateBundle(bundle) {
  const {api, source} = loadEngine(), calendar = validateCalendar(bundle.calendar, api);
  const grouped = validateBars(bundle.bars, calendar, api);
  const sessions = dates(PROTOCOL.start, PROTOCOL.end).filter(d=>calendar.get(d).status!=='CLOSED').map(date => {
    const row=calendar.get(date), previous=calendar.get(row.previousSessionDate);
    return {previous: grouped.get(previous.date)||[], bars:grouped.get(date)||[],
      meta:{dataKind:'HISTORICAL',date,open:Date.parse(row.openUtc),previousOpen:Date.parse(previous.openUtc),
        calendarStatus:row.status,previousCalendarStatus:previous.status,previousSessionVerified:true}};
  });
  const manifest = {strategyVersion:api.V,codeHash:source.hashes.derivative,
    parameterHash:sha256(JSON.stringify(api.CFG)), frozenAtUTC:'2026-10-14T15:28:20Z',
    dataSha256:bundle.manifest.bars.sha256,provider:bundle.manifest.provider,license:bundle.manifest.license,
    rawContract:PROTOCOL.contract,adjusted:false,calendarReviewed:true,provenanceReviewed:true};
  const scenarios = api.costScenarios().map(cost=>{
    const result=JSON.parse(JSON.stringify(api.runCampaign(sessions,'DEVELOPMENT',cost,manifest)));
    if(result.status!=='SCENARIO_REPLAY') fail('ENGINE_BLOCKED:'+result.reason);
    result.days.forEach((d,i)=>{d.date=sessions[i].meta.date;});
    result.summary=enrich(result);
    return result;
  });
  return {status:'DEVELOPMENT_SCENARIO_REPLAY',generatedAtUTC:new Date().toISOString(),
    protocol:PROTOCOL,protocolSha256:sha256(JSON.stringify(PROTOCOL)),sourceHashes:source.hashes,
    inputManifest:bundle.manifest,inputManifestSha256:bundle.manifestSha256,
    calendarRows:calendar.size,calendarClosedDates:[...calendar.values()].filter(r=>r.status==='CLOSED').map(r=>r.date),
    expectedDevelopmentSessions:sessions.length,normalizedBars:bundle.bars.length,
    historicalTradesTestedByScenario:scenarios.map(r=>r.summary.trades),
    actualAccountCosts:bundle.actualAccountCosts,scenarios,
    paperTradingStarted:false,liveExecutionEnabled:false,holdoutOpened:false,
    performanceClaimAllowed:false,
    limitations:['OHLC fills are hypothetical, not queue-verified.',
      'Bar availability is an assumed close, not measured delivery.',
      'Every fee/friction grid point is retained; fees and friction are assumptions.',
      'Fixed platform/data costs are not subtracted from grid returns.',
      'Drawdown is at completed-session endpoints, not intratrade.',
      'Caller provenance assertions need independent evidence review.',
      'This BC23-inspired subset is not all TJR rules or a Kalshi strategy.']};
}
export function blockedReport(reason, inputSupplied=false) {
  return {status:'BLOCKED',reason,generatedAtUTC:new Date().toISOString(),protocol:PROTOCOL,
    historicalTradesTested:0,historicalPnlUSD:null,holdoutOpened:inputSupplied?null:false,
    holdoutExposureStatus:inputSupplied?'UNVERIFIED_INPUT_REJECTED':'NOT_ACCESSED_NO_INPUT',holdoutReplayed:false,
    paperTradingStarted:false,liveExecutionEnabled:false,performanceClaimAllowed:false};
}
function main(argv) {
  let output;
  const i=argv.indexOf('--output');
  if(i>=0) output=argv[i+1];
  const bi=argv.indexOf('--bundle');
  let result;
  try {
    if(bi<0 || !argv[bi+1]) result=blockedReport('VERIFIED_ACTUAL_MNQZ2025_DATA_BUNDLE_MISSING');
    else result=evaluateBundle(readBundle(path.resolve(argv[bi+1])));
  } catch(error) {
    const reason=error instanceof InputError ? error.message :
      error?.code==='ENOENT' ? 'INPUT_FILE_MISSING' : 'INPUT_READ_OR_VALIDATION_FAILED';
    result=blockedReport(reason,bi>=0 && !!argv[bi+1]);
  }
  const formatted=JSON.stringify(result,null,2)+'\n';
  if(output) fs.writeFileSync(path.resolve(output),formatted,{flag:'wx'});
  else process.stdout.write(formatted);
  if(result.status==='BLOCKED') process.exitCode=2;
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) main(process.argv.slice(2));
