/** Offline source loading. The archived Page files are immutable inputs. */
import fs from 'node:fs';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ARCHIVE = path.resolve(HERE, '../tjr_mnq_2026-10-14');
export const ORIGINAL_VERSION = 'TJR_BC23_MNQZ25_SWEEP_BOS_v0.1';
export const VERSION = 'TJR_BC23_MNQZ25_SWEEP_BOS_v0.1.1_calendar';
export const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
const OLD = '  if(meta.calendarStatus!=="REGULAR"||meta.previousCalendarStatus!=="REGULAR")return out("SKIPPED","SHORT_OR_NONTRADING_SESSION");';
const NEW = '  const calendarStatuses=["REGULAR","EARLY_CLOSE","CLOSED"];\n' +
  '  if(!calendarStatuses.includes(meta.calendarStatus)||!calendarStatuses.includes(meta.previousCalendarStatus))return out("BLOCKED","CALENDAR_UNVERIFIED");\n' +
  OLD;
export function loadSources() {
  const manifest = JSON.parse(fs.readFileSync(path.join(ARCHIVE, 'SOURCE_MANIFEST.json')));
  const texts = {};
  for (const name of ['MAIN_HANDOFF.md', 'MNQ_PROTOTYPE.md']) {
    const raw = fs.readFileSync(path.join(ARCHIVE, name));
    if (sha256(raw) !== manifest.files_sha256[name]) throw Error(`ARCHIVE_HASH_MISMATCH:${name}`);
    texts[name] = raw.toString('utf8');
  }
  const blocks = name => [...texts[name].matchAll(/^```js\n([\s\S]*?)^```\s*$/gm)].map(m => m[1].replace(/\n$/, ''));
  const prototype = blocks('MNQ_PROTOTYPE.md'), feature = blocks('MAIN_HANDOFF.md');
  if (prototype.length !== 2 || feature.length !== 1) throw Error('SOURCE_BLOCK_COUNT_CHANGED');
  const originals = [feature.join('\n\n') + '\n', prototype.join('\n\n') + '\n'];
  for (let i = 0; i < 2; i++) {
    if (sha256(originals[i]) !== manifest.pages[i].extracted_javascript_sha256) throw Error('EXTRACTED_HASH_MISMATCH');
  }
  if (prototype[0].split(OLD).length !== 2) throw Error('PATCH_ANCHOR_CHANGED');
  const engine = prototype[0].replace(`const V="${ORIGINAL_VERSION}";`, `const V="${VERSION}";`).replace(OLD, NEW) + '\n';
  return {engine, originalEngine: prototype[0] + '\n', originalTests: prototype[1] + '\n',
    originalCombined: originals[1], featureCombined: originals[0], manifest,
    hashes: {originalCombined: sha256(originals[1]), originalEngine: sha256(prototype[0] + '\n'),
      originalTests: sha256(prototype[1] + '\n'), feature: sha256(originals[0]), derivative: sha256(engine)}};
}
export function engineContext(source) {
  const context = vm.createContext({}, {codeGeneration: {strings: false, wasm: false}});
  vm.runInContext(source, context, {timeout: 1000});
  return context;
}
export function loadEngine() {
  const source = loadSources();
  const context = engineContext(source.engine);
  const api = vm.runInContext('({simulateDay,summarize,costScenarios,runCampaign,local,CFG,V,CONTRACT})', context);
  return {api, source, context};
}
export function reproduceOriginalChecks() {
  const source = loadSources();
  const run = (code, report) => {
    const context = engineContext(code);
    return JSON.parse(vm.runInContext(`JSON.stringify(${report})`, context));
  };
  return {prototype: run(source.originalCombined, 'testReport'), feature: run(source.featureCombined, 'report'),
    derivativeCompatibility: run(source.engine + '\n' + source.originalTests, 'testReport'),
    hashes: source.hashes};
}
