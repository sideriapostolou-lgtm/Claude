"""Independent Kalshi polling and private-data request races, executed in Node."""
import shutil
from pathlib import Path

import pytest

from nightcrawler.world3d import _MODULE
from tests.test_world3d import _node

pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='Node is not installed')


def harness() -> str:
    start = _MODULE.index('  const TOWN_TRANSPORT =')
    end = _MODULE.index('  function setOffline(', start)
    return '''
const token = "";
let data = null, offline = true, authLocked = false, draws = 0;
const body = {classList:{remove(){}}};
function tycoonDraw(){draws++;}
function setOffline(){offline=true;}
function clearPageAccess(){TOWN_TRANSPORT.epoch++; TOWN_TRANSPORT.kalshiAt=-Infinity;
  TOWN_TRANSPORT.kalshiMoney=null; TOWN_TRANSPORT.kalshiFast=false; data=null; authLocked=true;}
''' + _MODULE[start:end]


def test_blocked_page_does_not_block_fast_money_or_reissue_fast_poll(tmp_path: Path) -> None:
    out = _node(harness() + '''
let pageResolve, townResolve, pages=0, towns=0;
function fetch(path){
  if(path==='api/page'){pages++; return new Promise(r=>pageResolve=r);}
  towns++; return new Promise(r=>townResolve=r);
}
const pending=fetchPage();
const fast=tickTown(); await tickTown();
townResolve({status:200,ok:true,json:async()=>({generated_at:200,money:{
 speeddesk:{kalshi_live:{profit_usd:null}},connections:{version:1,kalshi:{snapshot_as_of:12}}}})});
await fast;
const initial={data,draws,pages,towns};
pageResolve({status:200,ok:true,json:async()=>({generated_at:100,money:{
 polymarket:{as_of:50},speeddesk:{kalshi_live:{profit_usd:999}},connections:{kalshi:{snapshot_as_of:1}}}})});
const merged=mergeTownKalshi(await pending,false);
console.log(JSON.stringify({initial,merged}));
''', tmp_path)
    assert out['initial']['draws'] == 1
    assert out['initial']['pages'] == out['initial']['towns'] == 1
    assert 'generated_at' not in out['initial']['data']
    merged = out['merged']
    assert merged['generated_at'] == 100
    assert merged['money']['polymarket']['as_of'] == 50
    assert merged['money']['_town_kalshi_generated_at'] == 200
    assert merged['money']['speeddesk']['kalshi_live']['profit_usd'] is None
    assert merged['money']['connections']['kalshi']['snapshot_as_of'] == 12


def test_401_invalidates_inflight_success_until_new_authenticated_request(tmp_path: Path) -> None:
    out = _node(harness() + '''
let pageResolve, calls=0;
function fetch(path){calls++;
 if(calls===1)return new Promise(r=>pageResolve=r);
 if(calls===2)return Promise.resolve({status:401,ok:false});
 return Promise.resolve({status:200,ok:true,json:async()=>({generated_at:300,money:{}})});
}
data={money:{private:true}};
const old=fetchPage(); await tickTown();
const locked={data,authLocked};
pageResolve({status:200,ok:true,json:async()=>({money:{private:true}})});
const suppressed=await old;
await tickTown();
console.log(JSON.stringify({locked,suppressed,data,authLocked}));
''', tmp_path)
    assert out['locked'] == {'data': None, 'authLocked': True}
    assert out['suppressed'] is None
    assert out['authLocked'] is False
    assert out['data']['money'].get('private') is None


def test_timeout_aborts_and_releases_single_flight(tmp_path: Path) -> None:
    out = _node(harness() + '''
const timers=[];
globalThis.setTimeout=(fn)=>{timers.push(fn);return 1;};
globalThis.clearTimeout=()=>{};
let calls=0;
function fetch(path,opts){calls++;return new Promise((resolve,reject)=>{
 opts.signal.addEventListener('abort',()=>reject(new Error('aborted')));
});}
const first=tickTown(); await tickTown(); timers[0](); await first;
const second=tickTown(); timers[1](); await second;
console.log(JSON.stringify({calls,busy:TOWN_TRANSPORT.townBusy}));
''', tmp_path)
    assert out == {'calls': 2, 'busy': False}


def test_newer_full_response_cannot_replace_direct_source_with_old_checkpoint(tmp_path: Path) -> None:
    out = _node(harness() + r'''
const live = (at, profit) => ({as_of:at,profit_usd:profit});
const page = (generated, at, profit) => ({generated_at:generated,money:{
 speeddesk:{kalshi_live:live(at,profit)},connections:{version:1,kalshi:{as_of:at}},
 polymarket:{as_of:generated-20}}});
data=mergeTownKalshi(page(200,190,4),true);
const oldCheckpoint=mergeTownKalshi(page(300,100,99),false);
data=mergeTownKalshi(page(310,300,null),true);
const unknown=mergeTownKalshi(page(320,200,4),false);
console.log(JSON.stringify({oldCheckpoint,unknown}));
''', tmp_path)
    old = out['oldCheckpoint']
    assert old['generated_at'] == 300
    assert old['money']['speeddesk']['kalshi_live'] == {'as_of': 190, 'profit_usd': 4}
    assert old['money']['connections']['kalshi']['as_of'] == 190
    assert old['money']['polymarket']['as_of'] == 280
    new = out['unknown']['money']
    assert new['speeddesk']['kalshi_live'] == {'as_of': 300, 'profit_usd': None}
    assert new['connections']['kalshi']['as_of'] == 300
    assert new['_town_kalshi_generated_at'] == 310
