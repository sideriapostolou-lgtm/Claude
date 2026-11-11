"""The town acts out fresh venue receipts, never paper fills or old profits."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import world3d

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

PURE = world3d._M_BUSINESS.split("// >>> town activity (pure)", 1)[1].split("// <<< town activity", 1)[0]
FIXTURE = """
const active = { polymarket_us: true, kalshi: true };
function event(id, ts, more = {}) {
  return Object.assign({ id, ts, venue: "polymarket_us", kind: "fill", real: true,
    scope: "bot", current: true, text: "Confirmed fill", usd: null }, more);
}
const ids = rows => rows.map(e => e.id);
"""


def _node(tmp_path: Path, body: str, *, runtime: bool = False) -> dict[str, Any]:
    path = tmp_path / "business.mjs"
    path.write_text((RUNTIME + world3d._M_BUSINESS if runtime else PURE) + FIXTURE + body)
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30, check=True)
    out: dict[str, Any] = json.loads(result.stdout)
    return out


def test_first_batch_same_count_corrections_and_reconnect_do_not_replay(tmp_path: Path) -> None:
    out = _node(tmp_path, """
const memo = townActivityMemo();
const first = ids(townActivityFresh(memo, [event("old", 999)], active, 1000));
const next = ids(townActivityFresh(memo, [event("new", 1001)], active, 1002));
const again = ids(townActivityFresh(memo, [event("new", 1001, {kind:"settlement", usd:4})], active, 1003));
const down = ids(townActivityFresh(memo, [], {polymarket_us:false,kalshi:true}, 1004));
const reconnect = ids(townActivityFresh(memo, [event("during-outage", 1005)], active, 1006));
const late = ids(townActivityFresh(memo, [event("late", 1004)], active, 1007));
const after = ids(townActivityFresh(memo, [event("after", 1008)], active, 1009));
console.log(JSON.stringify({first,next,again,down,reconnect,late,after}));
""")
    assert out == {"first": [], "next": ["new"], "again": [], "down": [], "reconnect": [], "late": [], "after": ["after"]}


def test_new_venue_baselines_independently_and_empty_source_can_receive_events(tmp_path: Path) -> None:
    out = _node(tmp_path, """
const memo = townActivityMemo();
townActivityFresh(memo, [], {polymarket_us:true,kalshi:false}, 1000);
const firstKalshi = ids(townActivityFresh(memo, [event("pm",1001),event("k-old",1001,{venue:"kalshi"})],active,1002));
const nextKalshi = ids(townActivityFresh(memo,[event("k-new",1003,{venue:"kalshi"})],active,1004));
console.log(JSON.stringify({firstKalshi,nextKalshi}));
""")
    assert out == {"firstKalshi": ["pm"], "nextKalshi": ["k-new"]}


def test_rejects_paper_stale_future_unqualified_and_unknown_profit(tmp_path: Path) -> None:
    out = _node(tmp_path, """
const memo=townActivityMemo(); townActivityFresh(memo,[],active,1000);
const bad=[event("paper",1001,{real:false}), event("stale",1001), event("future",1080),
  event("unqualified",1069,{current:false}),event("missing-pnl",1069,{kind:"settlement"}),
  event("unknown-venue",1069,{venue:"international"}), event("unknown-scope",1069,{scope:"simulator"})];
const rejected=ids(townActivityFresh(memo,bad,active,1070));
const corrected=ids(townActivityFresh(memo,[event("unqualified",1069),event("missing-pnl",1069,{kind:"settlement",usd:1})],active,1071));
const valid=ids(townActivityFresh(memo,[event("live",1072)],active,1073));
const rewind=ids(townActivityFresh(memo,[event("rewind",1051)],active,1052));
console.log(JSON.stringify({rejected,corrected,valid,rewind}));
""")
    assert out == {"rejected": [], "corrected": [], "valid": ["live"], "rewind": []}


def test_bounded_activity_never_replays_ids_retired_from_memory(tmp_path: Path) -> None:
    out = _node(tmp_path, """
const memo=townActivityMemo(); townActivityFresh(memo,[],active,1000);
let largest=0;
for(let batch=0;batch<8;batch++) {
  const rows=Array.from({length:100},(_,i)=>event("receipt-"+(batch*100+i),1001+batch));
  largest=Math.max(largest,townActivityFresh(memo,rows,active,1002+batch).length);
}
const replay=ids(townActivityFresh(memo,[event("receipt-0",1001)],active,1010));
console.log(JSON.stringify({largest,size:memo.seen.size,replay}));
""")
    assert out == {"largest": 4, "size": 512, "replay": []}


def test_only_positive_bot_settlements_are_money_deliveries(tmp_path: Path) -> None:
    out = _node(tmp_path, """
const plans={};
for(const kind of ["order","fill","cancel","reject"]) plans[kind]=townActivityPlan(event(kind,1001,{kind,usd:8}));
for(const [key,usd,scope] of [["win",.27,"bot"],["loss",-.4,"bot"],["zero",0,"bot"],["owner",4,"owner"]])
  plans[key]=townActivityPlan(event(key,1001,{kind:"settlement",usd,scope}));
console.log(JSON.stringify(plans));
""")
    assert out["win"] == {"actor": "jet", "dest": "vault", "profit": 0.27, "gesture": "cheer"}
    assert out["fill"]["dest"] == "archive"
    assert out["loss"]["gesture"] == "worried"
    for key in ("order", "fill", "cancel", "reject", "loss", "zero", "owner"):
        assert out[key]["profit"] is None
    assert out["owner"]["actor"] == "mote"


RUNTIME = """
let now=1000, offline=false, town=true, flashUntil=0, drop=null;
Date.now=()=>now*1000;
const listeners={}, document={visibilityState:"visible",addEventListener:(key,fn)=>listeners[key]=fn};
const window={}, tycoonActive=()=>town, dropEl={style:{opacity:"0"}}, bubbles=[];
const actors=Object.fromEntries(["jet","mote","rook"].map(key=>[key,{
  key,name:key,queue:[],beats:[],actor:{},state:"home",action:null,carrying:null,heartUntil:0
}]));
const cube={mesh:{visible:false},flight:null,business:null};
const calls={speeches:[],gestures:[],deliveries:[],returns:0,ended:0};
function speak(actor,member,text,tone,seconds) {
  const small={textContent:""}, b={actor,el:{querySelector:()=>small,remove:()=>{}},small};
  bubbles.push(b);calls.speeches.push({actor:actor.key,text});return b;
}
const oneShot=(actor,gesture)=>calls.gestures.push([actor.key,gesture]);
const endOneShot=()=>calls.ended++;
const walkBack=actor=>{actor.state="back";calls.returns++};
const deliverCube=(actor,usd)=>calls.deliveries.push([actor.key,usd]);
const updateLamps=()=>{};
"""


def test_runtime_cancels_active_and_queued_receipts_on_correction_or_staleness(tmp_path: Path) -> None:
    out = _node(tmp_path, """
tycoonBusinessApply({activity:[],activitySources:active});
now=1002;const fill=event("fill",1001), win=event("win",1001,{venue:"kalshi",kind:"settlement",usd:.3});
tycoonBusinessApply({activity:[fill,win],activitySources:active});
const queued=actors.jet.queue.length, headers=bubbles.map(b=>b.small.textContent);
actors.jet.action=actors.jet.queue.shift();actors.jet.state="out";
const token=actors.jet.action.business;
cube.business=token;cube.mesh.visible=true;cube.flight={business:token};drop={business:token};dropEl.style.opacity="1";
now=1003;tycoonBusinessApply({activity:[event("fill",1001,{text:"Corrected receipt"}),win],activitySources:active});
tycoonBusinessFrame();
const corrected={state:actors.jet.state,callback:actors.jet.action.onArrive,queue:actors.jet.queue.length,
  cube:cube.mesh.visible,drop,ended:calls.ended};
now=1063;tycoonBusinessFrame();
console.log(JSON.stringify({queued,headers,corrected,remaining:actors.jet.queue.length,deliveries:calls.deliveries}));
""", runtime=True)
    assert out["queued"] == 2
    assert all("REAL BOT ACTIVITY" in header for header in out["headers"])
    assert out["corrected"]["state"] == "back"
    assert out["corrected"]["callback"] is None
    assert out["corrected"]["queue"] == 1
    assert not out["corrected"]["cube"] and out["corrected"]["drop"] is None
    assert out["remaining"] == 0 and out["deliveries"] == []


def test_runtime_positive_settlement_and_fill_are_distinct_and_disconnect_clears_them(tmp_path: Path) -> None:
    out = _node(tmp_path, """
tycoonBusinessApply({activity:[],activitySources:active});now=1002;
const fill=event("fill",1001), win=event("win",1001,{venue:"kalshi",kind:"settlement",usd:.3});
tycoonBusinessApply({activity:[fill,win],activitySources:active});
const receipt=actors.jet.queue.shift();receipt.onArrive(actors.jet);
const receiptProfit=calls.deliveries.length, gold=actors.jet.queue.shift();gold.onArrive(actors.jet);
const pulse=tycoonBusinessStatus("jet"), delivered=calls.deliveries.slice();
now=1003;offline=true;tycoonBusinessFrame();
const idle=tycoonBusinessStatus("jet");offline=false;now=1005;
tycoonBusinessApply({activity:[event("outage",1004,{kind:"settlement",usd:9})],activitySources:active});
console.log(JSON.stringify({receiptProfit,delivered,pulse,idle,after:window.__skyport.business.state()}));
""", runtime=True)
    assert out["receiptProfit"] == 0
    assert out["delivered"] == [["jet", 0.3]]
    assert out["pulse"] == "working" and out["idle"] == "idle"
    assert len(out["after"]["played"]) == 2 and out["after"]["queued"] == 0


def test_hidden_tab_reconnect_baselines_and_legacy_actions_never_enter_town(tmp_path: Path) -> None:
    out = _node(tmp_path, """
actors.jet.queue=[{dest:"vault",carry:"gold"},{ambient:true,dest:"kiosk"}];
tycoonBusinessApply({activity:[event("historic",999,{kind:"settlement",usd:10})],activitySources:active});
const initial=actors.jet.queue.slice();
document.visibilityState="hidden";listeners.visibilitychange();
now=1010;document.visibilityState="visible";
tycoonBusinessApply({activity:[event("hidden-win",1009,{kind:"settlement",usd:10})],activitySources:active});
console.log(JSON.stringify({initial,played:window.__skyport.business.state().played}));
""", runtime=True)
    assert out == {"initial": [{"ambient": True, "dest": "kiosk"}], "played": []}
    for name in ("onEvent", "onClosed", "chatter", "goalFree", "heartsStep"):
        source = world3d._MODULE.split(f"function {name}(", 1)[1]
        first_line = next(line.strip() for line in source.split("{", 1)[1].splitlines() if line.strip() and not line.strip().startswith("//"))
        assert 'typeof tycoonActive === "function" && tycoonActive()' in first_line
    assert world3d._MODULE.index("tycoonBusinessFrame();  // invalidate") < world3d._MODULE.index("updateActors(dt); updateCube(dt)")
