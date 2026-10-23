"""Console status lights inherit the crew report and cannot invent work offline."""

from pathlib import Path

from nightcrawler.worldtycoon_workflow import TYCOON_WORKFLOW
from tests.test_world3d import _js_body, _node


def test_console_and_dock_clear_current_status_without_replaying_receipts(tmp_path: Path) -> None:
    apply = _js_body(TYCOON_WORKFLOW, "  function tycoonWorkApply(")
    result = _node(r'''
const node = {dataset:{}, querySelector:()=>({textContent:""}),setAttribute:()=>{}};
const note={textContent:""};
const el=id=>id==="ty-work-note"?note:node;
const CAST={voss:{name:"Voss"}};
const station={material:{color:{setHex:n=>{station.color=n;}}}};
const TY_WORK={group:{visible:false},stations:{voss:station}};
const tycoonActive=()=>true;
let authLocked=false;
''' + apply + r'''
const s={crew:[{key:"voss",status:"working"}],focus:{current:true,state:"live",account:{locksOnly:false}}};
s.crew[0].status="unknown";tycoonWorkApply(s,false);const initial=station.status;
s.crew[0].status="stuck";tycoonWorkApply(s,false);const blocked=station.status;
s.crew[0].status="working";tycoonWorkApply(s,false);const current=station.status;
tycoonWorkApply(s,true);const offline=station.status;
authLocked=true;tycoonWorkApply(s,true);
console.log(JSON.stringify({initial,blocked,current,offline,locked:note.textContent,status:node.dataset.status}));
''', tmp_path)
    assert result == {"initial": "unknown", "blocked": "stuck", "current": "working", "offline": "unknown", "locked": "Locked · private data cleared", "status": "unknown"}
