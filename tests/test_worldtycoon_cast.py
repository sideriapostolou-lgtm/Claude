"""The town's toy costumes follow actors without becoming another activity source."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import world3d
from nightcrawler.worldtycoon_cast import TYCOON_CAST
from tests.test_world3d import _js_body


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_costumes_follow_existing_actors_without_mutating_work_or_routes(tmp_path: Path) -> None:
    three = (world3d.ASSET_DIR / "three.module.min.js").as_uri()
    helpers = tmp_path / "geometry.mjs"
    helpers.write_text((world3d.ASSET_DIR / "addons/utils/BufferGeometryUtils.js").read_text().replace(
        "from 'three'", f"from {json.dumps(three)}",
    ))
    harness = f"""
import * as THREE from {json.dumps(three)};
import {{ mergeGeometries }} from {json.dumps(helpers.as_uri())};
const keys = ["voss", "pip", "nyx", "rook", "mote", "jet"], ACTOR_KEYS = keys, actors = {{}};
const media = {{matches:false}}, window = {{matchMedia:()=>media}}, callbacks = {{}};
const BUS = {{on:(name,fn)=>callbacks[name]=fn}};
const cube = {{mesh:new THREE.Group(),flight:null,business:{{id:"existing-event"}},real:true}};
cube.mesh.visible=false;
let enabled = true, simT = 0;
const tycoonActive = ()=>enabled;
const paint = function (geometry, colour) {{
  const c = new THREE.Color(colour), values = new Float32Array(geometry.attributes.position.count * 3);
  for (let i=0;i<values.length;i+=3) {{ values[i]=c.r;values[i+1]=c.g;values[i+2]=c.b; }}
  geometry.setAttribute("color",new THREE.BufferAttribute(values,3));return geometry;
}};
keys.forEach(function(key) {{
  const group = new THREE.Group(), body = new THREE.Group();group.add(body);
  actors[key]={{key,group,body,st:{{walking:true,working:false}},groundSpeed:1.2,
    queue:[{{business:"real-existing-receipt"}}],pos:new THREE.Vector3(2,0,3),yaw:.5,head:new THREE.Object3D()}};
}});
const before = JSON.stringify(keys.map(k=>[actors[k].queue,actors[k].pos.toArray(),actors[k].yaw]));
{TYCOON_CAST}
callbacks.start();
const bounds=keys.map(function(key) {{
  const rig=TYCOON_CAST_RIGS[key], box=new THREE.Box3().setFromObject(rig.root);
  return {{key,min:box.min.y,max:box.max.y,height:tycoonCastHeight(key)}};
}});
for(let i=0;i<120;i++){{simT+=.016;callbacks.frame(.016);}}
const walked=TYCOON_CAST_RIGS.jet.legs[0].rotation.x;
const atRest=actors.jet.group.position.clone();actors.jet.group.position.set(5,2,-3);actors.jet.group.rotation.y=1.2;
actors.jet.group.updateMatrixWorld(true);
const follows=TYCOON_CAST_RIGS.jet.root.getWorldPosition(new THREE.Vector3()).distanceTo(actors.jet.group.position)<1e-10;
actors.jet.group.position.copy(atRest);
media.matches=true;const phase=TYCOON_CAST_RIGS.jet.phase;callbacks.frame(.016);
const calm={{phaseUnchanged:phase===TYCOON_CAST_RIGS.jet.phase,leg:TYCOON_CAST_RIGS.jet.legs[0].rotation.x}};
const carryActor=actors.jet, carryRig=TYCOON_CAST_RIGS.jet;
cube.mesh.visible=true;cube.mesh.position.set(8,9,10);callbacks.frame(.016);
const noncarrier=cube.mesh.position.toArray();
carryActor.carrying="gold";carryActor.st.carrying=true;callbacks.frame(.016);
const left=carryRig.hands[0].getWorldPosition(new THREE.Vector3()),right=carryRig.hands[1].getWorldPosition(new THREE.Vector3());
const expected=left.add(right).multiplyScalar(.5).addScaledVector(carryRig.root.getWorldDirection(new THREE.Vector3()),.035);
const aligned=cube.mesh.position.distanceTo(expected)<1e-10;
const inFront=carryActor.group.worldToLocal(cube.mesh.position.clone()).z>.35;
cube.mesh.visible=false;cube.mesh.position.set(3,4,5);callbacks.frame(.016);const hidden=cube.mesh.position.toArray();
cube.mesh.visible=true;cube.flight={{t:.2}};cube.mesh.position.set(5,6,7);callbacks.frame(.016);const flight=cube.mesh.position.toArray();
const carryUntouched=carryActor.carrying==="gold"&&cube.business.id==="existing-event"&&cube.flight.t===.2&&cube.real;
carryActor.carrying=null;carryActor.st.carrying=false;cube.flight=null;cube.mesh.visible=false;
const model=new THREE.Group();actors.jet.group.add(model);actors.jet.model=model;
callbacks.frame(.016);const swapped={{modelHidden:!model.visible,bodyHidden:!actors.jet.body.visible,
  costumeVisible:TYCOON_CAST_RIGS.jet.root.visible,parentVisible:actors.jet.group.visible}};
enabled=false;callbacks.frame(.016);
const restored={{modelVisible:model.visible,bodyHidden:!actors.jet.body.visible,costumeHidden:!TYCOON_CAST_RIGS.jet.root.visible}};
actors.jet.group.rotation.y=0;
const after=JSON.stringify(keys.map(k=>[actors[k].queue,actors[k].pos.toArray(),actors[k].yaw]));
console.log(JSON.stringify({{bounds,walked,follows,calm,swapped,restored,untouched:before===after,
  carry:{{noncarrier,aligned,inFront,hidden,flight,untouched:carryUntouched}},
  states:tycoonCastState()}}));
"""
    script = tmp_path / "cast.mjs"
    script.write_text(harness)
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, timeout=30)
    out: dict[str, Any] = json.loads(result.stdout)
    assert out["untouched"] and out["follows"] and out["walked"] != 0
    assert out["calm"] == {"phaseUnchanged": True, "leg": 0}
    assert out["carry"] == {"noncarrier": [8, 9, 10], "aligned": True, "inFront": True,
                            "hidden": [3, 4, 5], "flight": [5, 6, 7], "untouched": True}
    assert all(out["swapped"].values()) and all(out["restored"].values())
    assert len(out["states"]) == 6 and all(row["followsActor"] for row in out["states"])
    for row in out["bounds"]:
        assert row["min"] >= -.001, row
        assert row["max"] <= row["height"] + .01, row


def test_cast_hook_is_loaded_before_the_first_frame_without_a_new_data_source() -> None:
    assert TYCOON_CAST in world3d._MODULE
    assert world3d._MODULE.index(TYCOON_CAST) < world3d._MODULE.index(world3d._CINEMA_AT)
    assert 'BUS.on("frame", tycoonCastFrame)' in TYCOON_CAST
    assert not any(word in TYCOON_CAST for word in ("fetch(", "startWalk(", "queue.push(", "new WebSocket"))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_real_gestures_require_the_existing_current_pulse_and_clear_on_invalidation(tmp_path: Path) -> None:
    three = (world3d.ASSET_DIR / "three.module.min.js").as_uri()
    helpers = tmp_path / "geometry.mjs"
    helpers.write_text((world3d.ASSET_DIR / "addons/utils/BufferGeometryUtils.js").read_text().replace(
        "from 'three'", f"from {json.dumps(three)}",
    ))
    pure = world3d._M_BUSINESS.split("// >>> town activity (pure)", 1)[1].split("// <<< town activity", 1)[0]
    gates = "\n".join(_js_body(world3d._MODULE, start) for start in (
        "  function tycoonBusinessToken(e) {", "  function tycoonBusinessActionCurrent(token) {",
        "  function oneShot(a, name, maxSeconds) {",
    ))
    script = tmp_path / "gestures.mjs"
    script.write_text(f"""
import * as THREE from {json.dumps(three)};
import {{mergeGeometries}} from {json.dumps(helpers.as_uri())};
const media={{matches:false}},window={{matchMedia:()=>media}},document={{visibilityState:"visible"}},callbacks={{}};
const BUS={{on:(name,fn)=>callbacks[name]=fn}},cube={{mesh:{{visible:false}},flight:null}};
let now=1002,simT=0,enabled=true,offline=false;
Date.now=()=>now*1000;const tycoonActive=()=>enabled;
const paint=(g)=>{{g.setAttribute("color",new THREE.BufferAttribute(new Float32Array(g.attributes.position.count*3).fill(1),3));return g;}};
const ACTOR_KEYS=["jet","mote","rook"],actors={{}};
ACTOR_KEYS.forEach(key=>{{const group=new THREE.Group(),body=new THREE.Group();group.add(body);
  actors[key]={{key,group,body,st:{{}},state:"home",queue:[],beats:[],carrying:null}};}});
{pure}
const TY_BUSINESS={{pulses:{{}},latest:new Map(),sources:{{kalshi:true}}}};
{gates}
{TYCOON_CAST}
callbacks.start();
let serial=0;
const pulse=function(actor,kind="settlement",usd=.20,scope="bot"){{
  const event={{id:"e"+serial++,venue:"kalshi",kind,usd,scope,ts:now-1,real:true,current:true,text:"Actual receipt"}};
  const token=tycoonBusinessToken(event);TY_BUSINESS.latest.set(token.key,event);
  TY_BUSINESS.pulses[actor.key]={{token,until:now+7}};return event;
}};
const jet=actors.jet,rig=TYCOON_CAST_RIGS.jet;
const noPulse=oneShot(jet,"cheer",3);
pulse(jet);const accepted=oneShot(jet,"cheer",30);now+=.3;callbacks.frame(.016);
const realCheer=rig.gesture?.name==="cheer"&&rig.arms.every(arm=>arm.rotation.x<-2);
now+=3;callbacks.frame(.016);const expires=rig.gesture===null&&rig.arms.every(arm=>arm.rotation.x===0);
pulse(jet,"settlement",-.2);const lossCheer=oneShot(jet,"cheer",3),lossWorry=oneShot(jet,"worried",3);
now+=.3;callbacks.frame(.016);const worried=rig.head.rotation.z>0;
const lossShrug=oneShot(jet,"shrug",3);now+=.3;callbacks.frame(.016);const shrugged=rig.head.rotation.z<0;
pulse(jet,"fill",null);const fillCheer=oneShot(jet,"cheer",3),fillNod=oneShot(jet,"nod",3);
now+=.3;callbacks.frame(.016);const nodded=rig.head.rotation.x!==0;
pulse(jet,"settlement",1,"owner");const ownerCheer=oneShot(jet,"cheer",3);
const cleared=[];
for(const reason of ["source","correction","pulseReset","calm","hidden","offline","walking","carry"]){{
  now+=1;TY_BUSINESS.sources.kalshi=true;media.matches=false;document.visibilityState="visible";
  offline=false;jet.state="home";jet.carrying=null;pulse(jet);oneShot(jet,"cheer",3);now+=.3;callbacks.frame(.016);
  if(reason==="source")TY_BUSINESS.sources.kalshi=false;
  if(reason==="correction")TY_BUSINESS.latest.get(TY_BUSINESS.pulses.jet.token.key).usd=-1;
  if(reason==="pulseReset")TY_BUSINESS.pulses={{}};
  if(reason==="calm")media.matches=true;
  if(reason==="hidden")document.visibilityState="hidden";
  if(reason==="offline")offline=true;
  if(reason==="walking")jet.state="out";
  if(reason==="carry")jet.carrying="gold";
  callbacks.frame(.016);cleared.push(rig.gesture===null&&rig.arms.every(arm=>arm.rotation.x===0));
}}
jet.state="home";jet.carrying=null;offline=false;document.visibilityState="visible";
TY_BUSINESS.sources.kalshi=true;media.matches=true;pulse(jet);const calmRejected=oneShot(jet,"cheer",3)===false;
media.matches=false;const old=pulse(jet);old.ts=now-100;
const staleRejected=oneShot(jet,"cheer",3)===false;
let legacyPlayed=false;enabled=false;jet.actor={{spec:{{kind:"biped"}},play:()=>{{legacyPlayed=true;return true;}}}};
const legacy=oneShot(jet,"cheer");
console.log(JSON.stringify({{noPulse,accepted,realCheer,expires,lossCheer,lossWorry,worried,lossShrug,shrugged,
  fillCheer,fillNod,nodded,ownerCheer,cleared,calmRejected,staleRejected,legacy,legacyPlayed,
  noWorkCreated:ACTOR_KEYS.every(key=>actors[key].queue.length===0&&actors[key].beats.length===0)}}));
""")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, timeout=30)
    out = json.loads(result.stdout)
    assert not any(out[key] for key in ("noPulse", "lossCheer", "fillCheer", "ownerCheer"))
    assert all(out[key] for key in ("accepted", "realCheer", "expires", "lossWorry", "worried", "lossShrug",
                                    "shrugged", "fillNod", "nodded", "calmRejected", "staleRejected",
                                    "legacy", "legacyPlayed", "noWorkCreated"))
    assert all(out["cleared"])
