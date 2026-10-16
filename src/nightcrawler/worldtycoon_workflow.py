"""Futuristic desk presentation over the existing town and authoritative crew projection."""

TYCOON_WORKFLOW = r"""
  // Static wiring describes roles, never a simulated stream of orders or AI calls.
  const TY_WORK = { group: null, stations: {}, links: [] };
  function tycoonWorkBuild() {
    const group = new THREE.Group(); group.name = "tycoon:workstations";
    const shell = new THREE.MeshStandardMaterial({ color: 0x163d58, roughness: .35, metalness: .55 });
    const trim = new THREE.MeshBasicMaterial({ color: 0x60e6ed });
    const glass = new THREE.MeshBasicMaterial({ color: 0x45c9df, transparent: true, opacity: .23,
      side: THREE.DoubleSide, depthWrite: false });
    const box = function (parent, w, h, d, x, y, z, material) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
      mesh.position.set(x, y, z); parent.add(mesh); return mesh;
    };
    ["voss", "rook", "jet", "mote", "pip", "nyx"].forEach(function (key) {
      const room = actors[key].homeRoom, spot = SPOTS[room], home = NAV[spot.home].p;
      const desk = new THREE.Group(); desk.name = "tycoon:console:" + key;
      desk.position.copy(home); desk.rotation.y = spot.homeYaw;
      // Offset in front of the original worker, with no changes to navigation or hit targets.
      box(desk, 2.0, .14, .74, 0, .91, 1.10, shell);
      [-.78, .78].forEach(function (x) { box(desk, .10, .85, .50, x, .44, 1.10, shell); });
      box(desk, 2.02, .035, .05, 0, 1.00, 1.48, trim);
      box(desk, 1.65, .90, .035, 0, 1.67, 1.30, glass);
      [-.85, .85].forEach(function (x) { box(desk, .035, .96, .035, x, 1.67, 1.30, trim); });
      box(desk, 1.72, .035, .035, 0, 2.15, 1.30, trim);
      const statusMaterial = new THREE.MeshBasicMaterial({ color: 0x91a4ab });
      box(desk, .25, .055, .05, -.55, 1.95, 1.34, statusMaterial);
      // Three fixed receipt rows, without random charts or pretend typing.
      [1.77, 1.62, 1.47].forEach(function (y, i) {
        box(desk, .92 - i * .16, .035, .04, -.12, y, 1.34, trim);
      });
      group.add(desk); TY_WORK.stations[key] = { desk: desk, material: statusMaterial, status: "unknown" };
    });
    const origin = NAV[SPOTS[actors.voss.homeRoom].home].p;
    ["rook", "jet", "mote"].forEach(function (key) {
      const end = NAV[SPOTS[actors[key].homeRoom].home].p;
      const points = [new THREE.Vector3(origin.x, .045, origin.z),
        new THREE.Vector3(end.x, .045, origin.z), new THREE.Vector3(end.x, .045, end.z)];
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: 0x2c9daf, transparent: true, opacity: .55 }));
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
        node.setAttribute("aria-label", CAST[key].name + ": " + (words[status] || words.unknown)); }
    });
    const note = el("ty-work-note");
    note.textContent = typeof authLocked !== "undefined" && authLocked ? "Locked · private data cleared" : disconnected ? "Reconnecting · last records" : !s.focus.current ? "Waiting for fresh desk reports"
      : s.focus.state === "blocked" ? "Accounting checks · buys blocked"
      : s.focus.account.locksOnly ? "Existing pairs only · new bets stopped" : "Kalshi desk · reported work";
  }
"""
