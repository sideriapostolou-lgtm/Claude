"""Futuristic desk presentation over the existing town and authoritative crew projection."""

TYCOON_WORKFLOW = r"""
  // Static wiring describes roles, never a simulated stream of orders or AI calls.
  const TY_WORK = { group: null, stations: {}, links: [] };
  function tycoonWorkBuild() {
    const group = new THREE.Group(); group.name = "tycoon:workstations";
    const shell = new THREE.MeshStandardMaterial({ color: 0x849fa9, roughness: .38, metalness: .42 });
    const trim = new THREE.MeshBasicMaterial({ color: 0x7ce8e3 });
    const glass = new THREE.MeshBasicMaterial({ color: 0x153e52, transparent: true, opacity: .82,
      side: THREE.DoubleSide, depthWrite: false });
    const box = function (parent, w, h, d, x, y, z, material) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
      mesh.position.set(x, y, z); parent.add(mesh); return mesh;
    };
    ["voss", "rook", "jet", "mote", "pip", "nyx"].forEach(function (key) {
      const room = actors[key].homeRoom, spot = SPOTS[room], home = NAV[spot.home].p;
      const desk = new THREE.Group(); desk.name = "tycoon:console:" + key;
      desk.position.copy(home); desk.rotation.y = spot.homeYaw;
      box(desk, 3.75, .025, 3.45, 0, -.016, .60, shell);

      // A substantial workstation: chamfer-like tiered base, two static side screens,
      // inset keyboard and a generous central glass display. No decorative chart claims activity.
      box(desk, 2.8, .16, 1.05, 0, .91, 1.18, shell);
      box(desk, 2.55, .12, .88, 0, .79, 1.18, shell);
      [-1.08, 1.08].forEach(function (x) {
        box(desk, .19, .80, .76, x, .39, 1.18, shell);
        box(desk, .04, .62, .78, x, .44, 1.18, trim);
      });
      box(desk, 2.83, .035, .045, 0, 1.01, 1.72, trim);
      box(desk, .92, .024, .28, 0, 1.01, .97, shell);
      box(desk, 1.80, 1.04, .055, 0, 1.75, 1.50, shell);
      box(desk, 1.67, .91, .035, 0, 1.75, 1.54, glass);
      [-.89, .89].forEach(function (x) { box(desk, .035, 1.06, .035, x, 1.75, 1.56, trim); });
      box(desk, 1.83, .035, .035, 0, 2.28, 1.56, trim);
      [-1.20, 1.20].forEach(function (x) {
        box(desk, .49, .66, .08, x, 1.58, 1.45, shell);
        box(desk, .40, .54, .025, x, 1.58, 1.50, glass);
        box(desk, .30, .025, .035, x, 1.76, 1.53, trim);
        box(desk, .22, .025, .035, x, 1.64, 1.53, trim);
      });
      const statusMaterial = new THREE.MeshBasicMaterial({ color: 0x91a4ab });
      box(desk, .25, .055, .05, -.55, 2.05, 1.58, statusMaterial);
      // Three fixed receipt rows, without random charts or pretend typing.
      [1.86, 1.70, 1.54].forEach(function (y, i) {
        box(desk, .92 - i * .16, .035, .04, -.12, y, 1.58, trim);
      });
      group.add(desk); TY_WORK.stations[key] = { desk: desk, material: statusMaterial, status: "unknown" };
    });
    // Ordered stage connections are architectural wiring, never moving transaction trails.
    const stages = ["voss", "rook", "jet", "mote"];
    stages.slice(1).forEach(function (key, i) {
      const origin = NAV[SPOTS[actors[stages[i]].homeRoom].home].p;
      const end = NAV[SPOTS[actors[key].homeRoom].home].p;
      const points = [new THREE.Vector3(origin.x, .045, origin.z),
        new THREE.Vector3(end.x, .045, origin.z), new THREE.Vector3(end.x, .045, end.z)];
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: 0x4d929e, transparent: true, opacity: .08 }));
      line.name = "tycoon:role-link:" + key; group.add(line); TY_WORK.links.push(key);
    });
    TY_WORK.group = group; scene.add(group); return group;
  }
  function tycoonWorkApply(s, disconnected) {
    const group = TY_WORK.group || tycoonWorkBuild(); group.visible = tycoonActive();
    const words = { working: "Recent", waiting: "Waiting", idle: "Idle", stuck: "Blocked", unknown: "No report" };
    const colors = { working: 0x60e6ed, waiting: 0x89afba, idle: 0x89afba, stuck: 0xffb95d, unknown: 0x748590 };
    Object.keys(TY_WORK.stations).forEach(function (key) {
      const crew = s.crew.find(function (c) { return c.key === key; });
      const status = disconnected || !crew ? "unknown" : crew.status;
      const station = TY_WORK.stations[key]; station.status = status;
      station.material.color.setHex(colors[status] || colors.unknown);
      const node = el("ty-work-" + key);
      if (node) { node.dataset.status = status; node.querySelector("small").textContent = words[status] || words.unknown;
        node.setAttribute("aria-label", ({ voss: "Market feed", rook: "Safeguards", jet: "Orders", mote: "Results", pip: "Research", nyx: "Practice" }[key] || key) + ": " + (words[status] || words.unknown)); }
    });
    const note = el("ty-work-note");
    if (!note) return;
    note.textContent = typeof authLocked !== "undefined" && authLocked ? "Locked · private data cleared" : disconnected ? "Reconnecting · last records" : !s.focus.current ? "Waiting for fresh desk reports"
      : s.focus.state === "blocked" ? s.focus.account.dayStopped ? "Daily loss stop · buys paused" : "Accounting checks · buys blocked"
      : s.focus.account.locksOnly ? "Existing pairs only · new bets stopped" : "Kalshi desk · reported work";
  }
"""
