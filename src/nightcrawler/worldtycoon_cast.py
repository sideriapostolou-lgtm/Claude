"""Toy-like display rigs for the existing six actors, with no activity or movement source."""

TYCOON_CAST = r"""
  // >>> tycoon cast (display only)
  // These are costumes, not another set of agents: each follows its original actor's transform and
  // already-approved acting state. Nothing here schedules a trip, creates an event or changes a hit target.
  const TYCOON_CAST_HEIGHTS = { voss: 1.90, pip: 2.00, nyx: 1.35, rook: 2.80, mote: 1.60, jet: 1.60 };
  const TYCOON_CAST_RIGS = {}, TYCOON_CAST_SHAPES = {
    box: new THREE.BoxGeometry(1, 1, 1), wheel: new THREE.CylinderGeometry(1, 1, 1, 12),
    ear: new THREE.ConeGeometry(1, 1, 4),
  };
  const TYCOON_CAST_MAT = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .78, metalness: 0 });
  const TYCOON_CAST_GLASS = new THREE.MeshStandardMaterial({ color: 0xc5f4e8, transparent: true,
    opacity: .12, roughness: .15, metalness: 0, depthWrite: false });
  const TYCOON_CAST_CALM = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  const TYCOON_CAST_MATRIX = new THREE.Matrix4(), TYCOON_CAST_POSITION = new THREE.Vector3();
  const TYCOON_CAST_ROTATION = new THREE.Euler(), TYCOON_CAST_QUATERNION = new THREE.Quaternion();
  const TYCOON_CAST_SCALE = new THREE.Vector3();
  const TYCOON_CAST_LEFT = new THREE.Vector3(), TYCOON_CAST_RIGHT = new THREE.Vector3(), TYCOON_CAST_FORWARD = new THREE.Vector3();

  function tycoonCastPart(parent, name, pieces, at) {
    const group = new THREE.Group(); group.name = name;
    if (at) group.position.set(at[0], at[1], at[2]);
    const geometries = pieces.map(function (p) {
      const g = TYCOON_CAST_SHAPES[p[10] || "box"].clone();
      TYCOON_CAST_POSITION.set(p[4] || 0, p[5] || 0, p[6] || 0);
      TYCOON_CAST_ROTATION.set(p[7] || 0, p[8] || 0, p[9] || 0);
      TYCOON_CAST_QUATERNION.setFromEuler(TYCOON_CAST_ROTATION);
      TYCOON_CAST_SCALE.set(p[1], p[2], p[3]);
      TYCOON_CAST_MATRIX.compose(TYCOON_CAST_POSITION, TYCOON_CAST_QUATERNION, TYCOON_CAST_SCALE);
      g.applyMatrix4(TYCOON_CAST_MATRIX);
      paint(g, p[0]); return g;
    });
    const merged = mergeGeometries(geometries, false);
    geometries.forEach(function (g) { g.dispose(); });
    const mesh = new THREE.Mesh(merged, TYCOON_CAST_MAT); mesh.castShadow = true; mesh.receiveShadow = true;
    group.add(mesh); parent.add(group); return group;
  }
  function tycoonCastBiped(key, colours, scale) {
    const root = new THREE.Group(); root.name = "tycoon:cast:" + key; root.scale.setScalar(scale);
    const body = tycoonCastPart(root, "body", [
      [colours.body, .62, .58, .40, 0, .75, 0], [colours.trim, .65, .12, .43, 0, .48, 0],
      [colours.trim, .13, .19, .035, 0, .79, .217],
    ]);
    const arms = [-1, 1].map(function (s) {
      return tycoonCastPart(root, "arm", [[colours.body, .25, .40, .29, 0, -.19, 0],
        [colours.skin, .25, .18, .30, 0, -.44, .005]], [s * .45, .98, 0]);
    });
    const legs = [-1, 1].map(function (s) {
      return tycoonCastPart(root, "leg", [[colours.legs, .255, .30, .29, 0, -.17, 0],
        [colours.boot, .28, .12, .37, 0, -.355, .035]], [s * .17, .44, 0]);
    });
    const hands = arms.map(function (arm) {
      const hand = new THREE.Object3D(); hand.position.set(0, -.44, .035); arm.add(hand); return hand;
    });
    return { key: key, root: root, body: body, arms: arms, legs: legs, hands: hands,
      phase: 0, hidden: new Map(), head: null, tail: null };
  }
  function tycoonCastBuild(key) {
    const ink = 0x172e47, white = 0xfff4d8, brass = 0xe2a630;
    let rig;
    if (key === "voss") {
      rig = tycoonCastBiped(key, { body: 0x177c82, trim: brass, skin: 0x365ecb, legs: 0x294aa3, boot: 0xd99332 }, 1.08);
      rig.head = tycoonCastPart(rig.root, "owl head", [
        [0x365ecb, .86, .66, .61, 0, 0, 0], [0x365ecb, .18, .21, .22, -.32, .37, -.03, 0, 0, -.18],
        [0x365ecb, .18, .21, .22, .32, .37, -.03, 0, 0, .18],
        [0xc8ddfa, .35, .37, .05, -.205, -.025, .327], [0xc8ddfa, .35, .37, .05, .205, -.025, .327],
        [brass, .22, .24, .055, -.205, -.015, .363], [brass, .22, .24, .055, .205, -.015, .363],
        [ink, .095, .17, .06, -.19, -.01, .397], [ink, .095, .17, .06, .19, -.01, .397],
        [brass, .15, .18, .19, 0, -.19, .37, .20, 0, 0],
      ], [0, 1.25, 0]);
      tycoonCastPart(rig.body, "violet cape", [[0x693fa6, .69, .57, .09, 0, .76, -.25],
        [0x41c9df, .23, .29, .06, -.25, .72, .267, -.12, 0, -.10]]);
    } else if (key === "pip") {
      rig = tycoonCastBiped(key, { body: white, trim: 0x6e452c, skin: 0xec8938, legs: 0x507889, boot: 0x69472f }, 1.10);
      rig.head = tycoonCastPart(rig.root, "fox head", [
        [0xf1963e, .74, .57, .59, 0, 0, 0], [0xf1963e, .19, .31, .19, -.25, .41, 0, 0, Math.PI / 4, 0, "ear"],
        [0xf1963e, .19, .31, .19, .25, .41, 0, 0, Math.PI / 4, 0, "ear"],
        [white, .58, .19, .22, 0, -.18, .34], [ink, .14, .12, .085, 0, -.105, .485],
        [brass, .28, .24, .06, -.19, .09, .322], [brass, .28, .24, .06, .19, .09, .322],
        [0x428dc4, .20, .15, .07, -.19, .09, .362], [0x428dc4, .20, .15, .07, .19, .09, .362],
        [ink, .075, .085, .025, -.18, .065, .405], [ink, .075, .085, .025, .18, .065, .405],
      ], [0, 1.25, .02]);
      rig.tail = tycoonCastPart(rig.root, "fox tail", [[0xef913a, .25, .43, .27, 0, .17, -.14, -.55, 0, 0],
        [white, .26, .20, .28, 0, .39, -.28, -.55, 0, 0]], [0, .54, -.24]);
      tycoonCastPart(rig.body, "harness", [[0x774d31, .10, .53, .045, -.17, .79, .228, 0, 0, -.14]]);
    } else if (key === "rook") {
      rig = tycoonCastBiped(key, { body: 0x657f99, trim: brass, skin: 0x526c84, legs: 0x526c84, boot: 0x425b74 }, 1.65);
      rig.root.scale.x *= 1.16; rig.root.scale.z *= 1.12;
      rig.head = tycoonCastPart(rig.root, "golem head", [[0x708ba0, .77, .63, .62, 0, 0, 0],
        [0x4b6176, .79, .09, .10, 0, .08, .33], [0xffb32c, .19, .095, .055, -.19, .015, .39],
        [0xffb32c, .19, .095, .055, .19, .015, .39], [0x43586c, .35, .06, .035, 0, -.19, .335],
        [brass, .81, .14, .65, 0, -.33, 0], [0xe1a239, .045, .22, .025, .22, .2, .325, 0, 0, -.22],
      ], [0, 1.29, 0]);
      tycoonCastPart(rig.body, "stone seams", [[0xe6ac38, .04, .34, .03, -.10, .78, .217, 0, 0, -.23],
        [0x435c75, .16, .13, .05, .20, .92, .215]]);
    } else if (key === "jet") {
      rig = tycoonCastBiped(key, { body: 0xf4c331, trim: 0x596d81, skin: 0x596d81, legs: 0x566b7b, boot: 0xf0b930 }, .96);
      rig.head = tycoonCastPart(rig.root, "robot head", [[0xf4c331, .79, .54, .57, 0, 0, 0],
        [ink, .68, .27, .065, 0, .015, .303], [0x57dbec, .14, .10, .04, -.18, .035, .352],
        [0x57dbec, .14, .10, .04, .18, .035, .352], [0x6c7d8a, .09, .20, .13, -.44, -.015, 0],
        [0x6c7d8a, .09, .20, .13, .44, -.015, 0], [0x526b80, .06, .18, .06, .22, .32, -.04],
        [0x55c7dd, .13, .07, .13, .22, .43, -.04],
      ], [0, 1.18, .01]);
      tycoonCastPart(rig.body, "courier bag", [[0x95643e, .30, .34, .17, .30, .67, -.23],
        [0x845532, .07, .55, .04, .13, .74, .23, 0, 0, -.25], [white, .16, .10, .02, .3, .70, -.325]]);
    } else if (key === "nyx") {
      const root = new THREE.Group(); root.name = "tycoon:cast:nyx";
      rig = { key: key, root: root, arms: [], legs: [], phase: 0, hidden: new Map(), tail: null };
      rig.head = tycoonCastPart(root, "octopus head", [[0x9d78d3, .92, .79, .77, 0, 0, 0],
        [0xbba0e5, .86, .22, .75, 0, .29, -.015], [ink, .13, .18, .06, -.22, -.04, .408],
        [ink, .13, .18, .06, .22, -.04, .408], [brass, .28, .30, .055, .22, -.04, .403],
        [0x566785, .17, .18, .065, .22, -.04, .438], [white, .04, .065, .03, .205, -.01, .48],
        [0x7752ad, .17, .04, .03, 0, -.22, .4],
      ], [0, .94, 0]);
      for (let i = 0; i < 8; i++) {
        const angle = i * Math.PI / 4;
        const arm = tycoonCastPart(root, "tentacle", [[0x9672cb, .225, .25, .35, 0, .045, .12],
          [0xaa87dc, .25, .14, .32, 0, -.07, .36], [0xdbbce9, .12, .055, .14, 0, -.035, .38]],
        [Math.sin(angle) * .31, .145, Math.cos(angle) * .31]);
        arm.rotation.y = angle; rig.arms.push(arm);
      }
    } else if (key === "mote") {
      const root = new THREE.Group(); root.name = "tycoon:cast:mote";
      rig = { key: key, root: root, arms: [], legs: [], wheels: [], phase: 0, hidden: new Map(), tail: null };
      tycoonCastPart(root, "bell cart", [[brass, .84, .12, .69, 0, .24, 0],
        [0x876938, .85, .075, .70, 0, .31, 0], [brass, .83, .08, .68, 0, 1.40, 0],
        [brass, .55, .065, .45, 0, 1.465, 0], [brass, .14, .08, .13, 0, 1.515, 0]]);
      [-1, 1].forEach(function (s) { [-1, 1].forEach(function (z) {
        const wheel = tycoonCastPart(root, "cart wheel", [[0x526e72, .12, .10, .12, 0, 0, 0, 0, 0, Math.PI / 2, "wheel"]], [s * .42, .125, z * .225]);
        rig.wheels.push(wheel);
        tycoonCastPart(root, "bell corner", [[brass, .035, 1.05, .035, s * .36, .86, z * .29]]);
      }); });
      rig.head = tycoonCastPart(root, "mint spirit", [[0x7cdac0, .57, .64, .45, 0, 0, 0],
        [0x9ae8d1, .17, .17, .16, -.17, .33, -.04], [0x9ae8d1, .17, .17, .16, .17, .33, -.04],
        [ink, .07, .12, .035, -.14, .04, .24], [ink, .07, .12, .035, .14, .04, .24],
        [0x338d83, .11, .035, .03, 0, -.12, .24], [white, .26, .17, .08, 0, -.26, .285],
      ], [0, .82, 0]);
      const glass = new THREE.Mesh(TYCOON_CAST_SHAPES.box, TYCOON_CAST_GLASS);
      glass.scale.set(.74, 1.05, .60); glass.position.y = .865; glass.renderOrder = 2; root.add(glass);
    }
    if (!rig) return null;
    rig.root.userData.actorKey = key; rig.root.userData.visualOnly = true;
    const actor = actors[key]; actor.group.add(rig.root); actor.tycoonVisualHeight = TYCOON_CAST_HEIGHTS[key];
    TYCOON_CAST_RIGS[key] = rig; return rig;
  }
  function tycoonCastHeight(key) { return TYCOON_CAST_HEIGHTS[key] || 0; }
  function tycoonCastOneShot(a, name, maxSeconds) {
    if (!tycoonActive() || TYCOON_CAST_CALM.matches || !a || a.state === "out" || a.state === "back"
        || a.carrying || !["cheer", "nod", "worried", "shrug"].includes(name)) return false;
    const pulse = TY_BUSINESS.pulses[a.key], now = Date.now() / 1000;
    if (!pulse || now >= pulse.until || !tycoonBusinessActionCurrent(pulse.token)) return false;
    const event = TY_BUSINESS.latest.get(pulse.token.key);
    const win = event.scope === "bot" && event.kind === "settlement" && event.usd > 0;
    const caution = event.kind === "reject" || (event.kind === "settlement" && event.usd < 0);
    if (name === "cheer" && !win || (name === "worried" || name === "shrug") && !caution) return false;
    const rig = TYCOON_CAST_RIGS[a.key] || tycoonCastBuild(a.key);
    if (!rig) return false;
    const duration = typeof maxSeconds === "number" && isFinite(maxSeconds) && maxSeconds > 0
      ? Math.min(3, maxSeconds) : 2.4;
    rig.gesture = { name: name, pulse: pulse, at: now, until: Math.min(now + duration, pulse.until, pulse.token.expires) };
    return true;
  }
  function tycoonCastGesture(a, rig) {
    const shot = rig.gesture;
    if (!shot) return;
    const now = Date.now() / 1000;
    if (!tycoonActive() || TYCOON_CAST_CALM.matches || now < shot.at || now >= shot.until
        || TY_BUSINESS.pulses[a.key] !== shot.pulse || !tycoonBusinessActionCurrent(shot.pulse.token)
        || a.state === "out" || a.state === "back" || a.carrying) { rig.gesture = null; return; }
    const wave = Math.sin((now - shot.at) * 6), edge = Math.min(1, (now - shot.at) * 6, (shot.until - now) * 6);
    if (shot.name === "cheer") {
      rig.arms.forEach(function (arm, i) { arm.rotation.x = (-2.55 + wave * .08) * edge; arm.rotation.z = (i ? -.24 : .24) * edge; });
      rig.head.rotation.x = -.12 * edge;
    } else if (shot.name === "nod") rig.head.rotation.x = wave * .19 * edge;
    else {
      rig.head.rotation.z = (shot.name === "worried" ? .12 : -.13) * edge;
      rig.head.rotation.x = (shot.name === "worried" ? .14 : -.04) * edge;
      if (rig.hands) rig.arms.forEach(function (arm, i) {
        arm.rotation.x = -.72 * edge; arm.rotation.z = (i ? -.43 : .43) * edge;
      });
    }
  }
  function tycoonCastCarry(a, rig) {
    // Only reposition the already-visible receipt/profit cube belonging to the existing carrier. Its event
    // validity, colour, flight, creation and disappearance remain entirely with the original business logic.
    if (!a.carrying || !cube.mesh.visible || cube.flight || !rig.hands) return;
    rig.hands[0].getWorldPosition(TYCOON_CAST_LEFT); rig.hands[1].getWorldPosition(TYCOON_CAST_RIGHT);
    rig.root.getWorldDirection(TYCOON_CAST_FORWARD);
    cube.mesh.position.addVectors(TYCOON_CAST_LEFT, TYCOON_CAST_RIGHT).multiplyScalar(.5)
      .addScaledVector(TYCOON_CAST_FORWARD, .035);
    cube.mesh.scale.setScalar(Math.max(.7, Math.min(1.15, TYCOON_CAST_LEFT.distanceTo(TYCOON_CAST_RIGHT) / .36)));
  }
  function tycoonCastFrame(dt) {
    const enabled = tycoonActive(), calm = TYCOON_CAST_CALM.matches;
    ACTOR_KEYS.forEach(function (key) {
      const a = actors[key], rig = TYCOON_CAST_RIGS[key] || (enabled && tycoonCastBuild(key));
      if (!rig) return;
      rig.root.visible = enabled;
      if (!enabled) {
        rig.gesture = null;
        rig.hidden.forEach(function (wasVisible, object) { object.visible = object === a.body && a.model ? false : wasVisible; });
        rig.hidden.clear(); return;
      }
      // Loading/failure callbacks may swap the old drawing and GLB between frames. Hide whichever exists
      // immediately before rendering, without touching the actor parent, motion adapter, anchors or callbacks.
      [a.body, a.model].forEach(function (object) {
        if (!object) return;
        if (!rig.hidden.has(object)) rig.hidden.set(object, object.visible);
        object.visible = false;
      });
      const st = a.st || {}, walking = st.walking && dt > 0 && !calm;
      rig.phase += walking ? Math.min(dt, .1) * Math.max(0, a.groundSpeed || 0) * 7 : 0;
      const stride = walking ? Math.sin(rig.phase) * .30 : 0;
      const work = st.working && !calm && dt > 0 ? Math.sin(simT * 4.5) * .09 : 0;
      rig.legs.forEach(function (leg, i) {
        const angle = stride * (i ? -1 : 1); leg.rotation.x = angle;
        // Keep the lowest shoe corner on the existing actor's floor throughout the swing.
        leg.position.y = .44 + Math.max(0, .20 * Math.abs(Math.sin(angle)) - .42 * (1 - Math.cos(angle)));
      });
      rig.arms.forEach(function (arm, i) {
        if (key === "nyx") { arm.position.y = .145 + (walking ? Math.max(0, Math.sin(rig.phase + i * Math.PI / 4)) * .06 : 0); return; }
        arm.rotation.x = st.carrying ? -1.04 : st.working ? -.35 + work * (i ? -1 : 1) : stride * (i ? 1 : -1);
        arm.rotation.z = st.carrying ? (i ? -.58 : .58) : 0;
      });
      if (rig.tail) rig.tail.rotation.y = walking ? Math.sin(rig.phase * .5) * .16 : 0;
      if (rig.wheels) rig.wheels.forEach(function (wheel) { wheel.rotation.x = calm ? 0 : rig.phase * .75; });
      if (rig.head) rig.head.rotation.set(0, calm ? 0 : Math.max(-.25, Math.min(.25, a.lookYaw || 0)), 0);
      tycoonCastGesture(a, rig);
      tycoonCastCarry(a, rig);
    });
  }
  function tycoonCastState() {
    return Object.keys(TYCOON_CAST_RIGS).map(function (key) {
      const rig = TYCOON_CAST_RIGS[key];
      return { key: key, visible: rig.root.visible, height: tycoonCastHeight(key),
        followsActor: rig.root.parent === actors[key].group, parts: rig.root.children.length,
        gesture: rig.gesture ? rig.gesture.name : null };
    });
  }
  BUS.on("start", function () { tycoonCastFrame(0); }); BUS.on("frame", tycoonCastFrame);
  window.__skyport = Object.assign(window.__skyport || {}, { cast: { state: tycoonCastState } });
  // <<< tycoon cast
"""
