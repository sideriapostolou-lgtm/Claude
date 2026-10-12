"""A landscaped toy town over the existing set; all business activity remains ledger driven."""

TYCOON_PARK = r"""
  // Colour identifies a department, never a simulated flow of money. The same cast, feet, desk coordinates
  // and walking graph survive the park treatment. Decorative buildings cannot send an order or invent work.
  const TYCOON_PARK_COLORS = { table: 0x38b8ad, workshop: 0xf59b54, den: 0xa382dc,
    vault: 0x69afd4, archive: 0x6bb98d, dock: 0xebbf4b, observatory: 0x829cdc };
  const TYCOON_PARK_STATE = { group: null, routes: [], departments: [], flags: [], upgrades: [],
    growth: { qualified: false, level: null, pnl_usd: null }, hidden: [], hiddenSet: new Set() };
  const TYCOON_DAY_DIRECTION = new THREE.Vector3(-.45, .85, .4).normalize();

  function tycoonParkBuild() {
    const group = new THREE.Group(); group.name = "tycoon:park";
    const ground = [], signs = [], landscape = [], buildings = [], white = 0xfff5dc, paving = 0xf3dfba;
    const put = function (list, geo, colour, point, yaw) {
      if (yaw) geo.rotateY(yaw);
      if (point) geo.translate(point.x, point.y, point.z);
      paint(geo, colour); list.push(prep(geo));
    };
    const v = function (x, y, z) { return new THREE.Vector3(x, y, z); };
    const disc = function (radius, colour, point) {
      put(ground, new THREE.CircleGeometry(radius, 64).rotateX(-Math.PI / 2), colour, point);
    };
    const rectangle = function (width, depth, colour, point, yaw) {
      put(ground, new THREE.PlaneGeometry(width, depth).rotateX(-Math.PI / 2), colour, point, yaw);
    };
    const box = function (list, width, height, depth, colour, point, yaw) {
      put(list, new THREE.BoxGeometry(width, height, depth), colour, point, yaw);
    };
    const tree = function (x, z, size) {
      put(landscape, new THREE.CylinderGeometry(0.11 * size, 0.16 * size, 1.7 * size, 6), 0x946747, v(x, .78 * size, z));
      [[0, 2.1, 0, .95], [-.55, 1.82, .2, .65], [.55, 1.95, -.2, .66]].forEach(function (p, i) {
        const geometry = new THREE.IcosahedronGeometry(p[3] * size, 1);
        geometry.scale(1, 1.12, 1);
        put(landscape, geometry, [0x73ad52, 0x91c76a, 0x66a350][i], v(x + p[0] * size, p[1] * size, z + p[2] * size));
      });
    };
    const fence = function (x, z, length, yaw) {
      const at = function (a, y) { return v(a, y, 0).applyAxisAngle(v(0, 1, 0), yaw).add(v(x, 0, z)); };
      for (let a = -length / 2; a <= length / 2 + .01; a += 1.4) {
        box(landscape, .13, .92, .13, white, at(a, .40), yaw);
        put(landscape, new THREE.ConeGeometry(.12, .17, 4), white, at(a, .94), yaw + Math.PI / 4);
      }
      [.34, .68].forEach(function (y) { box(landscape, length, .11, .08, white, at(0, y), yaw); });
    };
    const badge = function (point, yaw, colour, room) {
      const at = function (x, y, z) { return v(x, y, z).applyAxisAngle(v(0, 1, 0), yaw).add(point); };
      put(signs, new THREE.CylinderGeometry(0.045, 0.06, 2.65, 8), white, at(0, 1.325, 0));
      put(signs, new THREE.SphereGeometry(0.10, 8, 6), colour, at(0, 2.73, 0));
      box(signs, .95, .64, .08, colour, at(.44, 2.26, 0), yaw);
      box(signs, .14, .64, .09, white, at(.18, 2.26, 0), yaw);
      TYCOON_PARK_STATE.flags.push({ room: room, position: point.toArray() });
    };

    // A connected lawn replaces the visual gaps between floating islets. It stays below every original floor,
    // foot and contact shadow. Alternating mowing strips are decorative, not lots for sale or profit counters.
    box(landscape, 56, 3.0, 50, 0xaf8b63, v(2, -1.65, -3));
    box(landscape, 56.2, .24, 50.2, 0x71a950, v(2, -.27, -3));
    for (let row = 0; row < 10; row++) for (let column = 0; column < 12; column++) {
      rectangle(56 / 12 + .002, 5.002, (row + column) % 2 ? 0x6fac49 : 0x79b651,
        v(-26 + (column + .5) * 56 / 12, -.145, -28 + (row + .5) * 5));
    }
    DISCS.forEach(function (d, i) {
      disc(d[2] - .09, i % 3 === 0 ? 0x79b651 : i % 3 === 1 ? 0x72ae48 : 0x84bf5b,
        v(d[0], d[3] + .002 - i * .00003, d[1]));
    });
    disc(COURT_R + .18, paving, v(0, .008, 0));
    put(ground, new THREE.RingGeometry(COURT_R - .12, COURT_R + .12, 80).rotateX(-Math.PI / 2),
      TYCOON_PARK_COLORS.table, v(0, .009, 0));
    put(ground, new THREE.RingGeometry(2.42, 2.53, 64).rotateX(-Math.PI / 2),
      TYCOON_PARK_COLORS.table, v(0, .009, 0));
    rectangle(3.5, 8.4, white, v(0, -.12, 17.7));
    rectangle(3.18, 8.4, paving, v(0, -.11, 17.7));

    // Cutaway pavilions: bold roof-edge silhouettes and striped canopies make each department legible from a
    // phone. The work area remains open; posts are outside the doorway and no navigation node moves.
    const dimensions = { workshop: [7.5, 7], den: [7.5, 7], archive: [7, 6.4], vault: [7, 6.4] };
    Object.keys(ROOMS).forEach(function (key) {
      const frame = RF[key], colour = TYCOON_PARK_COLORS[key], size = dimensions[key];
      if (colour == null) return;
      TYCOON_PARK_STATE.departments.push(key);
      if (frame && size) {
        const pale = new THREE.Color(colour).lerp(new THREE.Color(white), .82), w = size[0], d = size[1];
        rectangle(w + .45, d + .45, colour, frame.at(0, .004, 0), frame.yaw);
        rectangle(w - .03, d - .03, pale, frame.at(0, .006, 0), frame.yaw);
        rectangle(3.8, 1.9, white, frame.at(0, .008, d / 2 + .7), frame.yaw);
        rectangle(3.5, 1.65, colour, frame.at(0, .009, d / 2 + .7), frame.yaw);
        rectangle(1.45, 1.68, paving, frame.at(0, .010, d / 2 + .7), frame.yaw);
        badge(frame.at(-2.65, 0, d / 2 + .9), frame.yaw, colour, key);
        // A short, solid back facade gives the miniature a recognisable building profile while the roof is off.
        box(buildings, w + .54, .94, .54, pale, frame.at(0, 1.16, -d / 2), frame.yaw);
        box(buildings, w + .9, .24, 1.1, colour, frame.at(0, 1.76, -d / 2), frame.yaw);
        box(buildings, w + 1.0, .07, 1.17, white, frame.at(0, 1.91, -d / 2), frame.yaw);
        [-1, 1].forEach(function (sign) {
          box(buildings, .19, 1.92, .19, white, frame.at(sign * (w / 2 + .04), .96, -d / 2), frame.yaw);
          box(buildings, .48, .13, d - .12, colour, frame.at(sign * w / 2, .82, 0), frame.yaw);
          box(buildings, .16, 2.22, .16, white, frame.at(sign * 1.55, 1.11, d / 2 + 1.24), frame.yaw);
        });
        for (let stripe = 0; stripe < 8; stripe++) {
          const x = (stripe - 3.5) * .43, shade = stripe % 2 ? white : colour;
          box(buildings, .432, .15, 1.65, shade, frame.at(x, 2.27, d / 2 + .60), frame.yaw);
          box(buildings, .432, .23, .12, shade, frame.at(x, 2.13, d / 2 + 1.43), frame.yaw);
        }
        // Small department-colour planter boxes finish the corners without surrounding the worker in labels.
        [-1, 1].forEach(function (sign) {
          box(buildings, .85, .34, .60, colour, frame.at(sign * (w / 2 - .7), .17, d / 2 + .72), frame.yaw);
          put(buildings, new THREE.IcosahedronGeometry(.44, 1), 0x73af62,
            frame.at(sign * (w / 2 - .7), .60, d / 2 + .72));
        });
      } else if (key === "observatory" && frame) {
        disc(5.48, paving, frame.at(0, .006, 0));
        put(ground, new THREE.RingGeometry(5.23, 5.43, 64).rotateX(-Math.PI / 2), colour, frame.at(0, .008, 0));
        badge(frame.at(-2.15, 0, 4.95), frame.yaw, colour, key);
      } else if (key === "dock") {
        rectangle(4.75, 2.22, paving, v(23.2, .009, -1.5));
        rectangle(4.75, .18, colour, v(23.2, .010, -2.5));
        rectangle(4.75, .18, colour, v(23.2, .010, -.5));
        badge(v(24.95, 0, -2.37), 0, colour, key);
      }
    });

    // Path edges follow the actual walk graph. No decorative parcel implies an order; actors move only through
    // their existing event handler. Stairs retain their original treads and the courtyard remains one open plaza.
    Object.keys(NAV).forEach(function (key) {
      NAV[key].edges.forEach(function (other) {
        if (key >= other || key.startsWith("tb") || other.startsWith("tb")) return;
        const a = NAV[key].p, b = NAV[other].p;
        if (Math.abs(a.y - b.y) > .05) return;
        const length = a.distanceTo(b); if (length < .05) return;
        const midpoint = a.clone().add(b).multiplyScalar(.5), yaw = Math.atan2(b.x - a.x, b.z - a.z);
        midpoint.y += .0111; rectangle(1.26, length + .11, white, midpoint, yaw);
        midpoint.y += .0004; rectangle(1.08, length + .04, paving, midpoint, yaw);
        TYCOON_PARK_STATE.routes.push([key, other]);
      });
    });
    [-23, -19, -15, -11, -7, 7, 11, 15, 19, 23, 27].forEach(function (x, i) { tree(x, -24 + i % 2, .95 + i % 3 * .15); });
    [-18, -12, -6, 0, 6, 12, 17].forEach(function (z, i) { tree(-23, z, 1 + i % 2 * .22); });
    [-18, -12, 7, 13, 18].forEach(function (z, i) { tree(27, z, .96 + i % 2 * .18); });
    fence(-23.2, -3, 44, Math.PI / 2); fence(27.6, -3, 44, Math.PI / 2);
    fence(2, -25.2, 50.4, 0); fence(-12.4, 19.3, 19.6, 0); fence(14.4, 19.3, 23.6, 0);
    [-1, 1].forEach(function (sign) {
      box(buildings, .62, 3.4, .68, white, v(sign * 2.18, 1.56, 19.3));
      box(buildings, .78, .20, .84, TYCOON_PARK_COLORS.table, v(sign * 2.18, 3.31, 19.3));
    });
    box(buildings, 5.2, .62, .52, TYCOON_PARK_COLORS.table, v(0, 3.47, 19.3));
    box(buildings, 5.42, .12, .76, white, v(0, 3.84, 19.3));

    const merge = function (list, name, cast, parent) {
      const geometry = mergeGeometries(list, false); if (!geometry) return null;
      const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .9,
        metalness: 0, depthWrite: !!cast, polygonOffset: !cast, polygonOffsetFactor: 0, polygonOffsetUnits: -1 });
      const mesh = new THREE.Mesh(geometry, material); mesh.name = name;
      if (!cast) mesh.renderOrder = 1;
      mesh.receiveShadow = true; mesh.castShadow = !!cast && Q.shadows;
      mesh.matrixAutoUpdate = false; mesh.updateMatrix(); (parent || group).add(mesh);
      list.forEach(function (geo) { geo.dispose(); }); return mesh;
    };
    merge(ground, "tycoon:lawns-and-paving", false); merge(signs, "tycoon:department-pennants", true);
    merge(landscape, "tycoon:park-landscape", true); merge(buildings, "tycoon:park-pavilions", true);

    // Five optional little terrace gardens show explicitly labelled, earned daily milestones. These do not
    // appreciate with cash deposits, elapsed viewing time, practice results or the owner's own account trades.
    for (let level = 0; level < 5; level++) {
      const geometry = [], x = -18.6 + level * 3.0, z = -18.5, tint = [0xeec061, 0xeab071, 0xb9cf88, 0x8cc2b0, 0xb5a2d4][level];
      box(geometry, 2.55, .18, 2.2, white, v(x, .00, z));
      box(geometry, 2.28, .12, 1.93, tint, v(x, .15, z));
      box(geometry, 1.52, .13, .46, 0xc38f56, v(x, .62, z + .34));
      [-.55, .55].forEach(function (offset) {
        box(geometry, .14, .44, .33, white, v(x + offset, .36, z + .34));
        put(geometry, new THREE.CylinderGeometry(.26, .22, .30, 8), tint, v(x + offset, .34, z - .60));
        put(geometry, new THREE.IcosahedronGeometry(.36, 1), 0x64a765, v(x + offset, .73, z - .60));
        put(geometry, new THREE.IcosahedronGeometry(.16, 0), [0xf6d67a, 0xf2a48f, 0xd4b1e8][level % 3], v(x + offset, 1.05, z - .60));
      });
      const mesh = merge(geometry, "tycoon:earned-garden-" + (level + 1), true);
      if (mesh) { mesh.visible = false; TYCOON_PARK_STATE.upgrades.push(mesh); }
    }
    group.visible = false; scene.add(group); TYCOON_PARK_STATE.group = group;
    return group;
  }
  function tycoonParkApply(summary) {
    const growth = summary && summary.growth, level = growth && growth.level;
    const qualified = !!(growth && growth.qualified === true && typeof level === "number"
      && Number.isInteger(level) && level >= 0 && level <= 5 && typeof growth.pnl_usd === "number" && isFinite(growth.pnl_usd));
    const wasQualified = TYCOON_PARK_STATE.growth.qualified;
    TYCOON_PARK_STATE.growth = { qualified: qualified, level: qualified ? level : null,
      pnl_usd: qualified ? growth.pnl_usd : null };
    const calm = typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    TYCOON_PARK_STATE.upgrades.forEach(function (mesh, i) {
      const show = qualified && i < level;
      if (show && !mesh.visible) {
        // Existing progress appears complete on arrival; only a newly earned milestone grows during the visit.
        mesh.userData.growth = wasQualified && !calm ? 0 : 1;
        mesh.scale.y = Math.max(.01, mesh.userData.growth); mesh.updateMatrix();
      }
      mesh.visible = show;
    });
  }
  function tycoonParkHideLegacy(on) {
    if (!on) {
      TYCOON_PARK_STATE.hidden.forEach(function (row) { row.node.layers.mask = row.mask; });
      TYCOON_PARK_STATE.hidden.length = 0; TYCOON_PARK_STATE.hiddenSet.clear(); return;
    }
    const hide = function (node) {
      if (!node || !node.isObject3D) return;
      node.traverse(function (part) {
        if (!TYCOON_PARK_STATE.hiddenSet.has(part)) {
          TYCOON_PARK_STATE.hidden.push({ node: part, mask: part.layers.mask }); TYCOON_PARK_STATE.hiddenSet.add(part);
        }
        part.layers.set(2);
      });
    };
    // The old tower and villagers use UTC profit; the separate arena buildings use practice results. Neither
    // becomes part of this Pacific-day town's growth. Layers keep later animation ticks from revealing them.
    if (typeof GP !== "undefined") {
      Object.values(GP).forEach(hide);
      if (GP.stalls) GP.stalls.forEach(function (stall) { hide(stall.shutter); hide(stall.goods); });
    }
    if (typeof TP !== "undefined") {
      Object.values(TP).forEach(hide);
      if (TP.rings) TP.rings.forEach(function (ring) { hide(ring.m); });
    }
    if (typeof TY_TOWN_STATIC !== "undefined") hide(TY_TOWN_STATIC);
    if (typeof props !== "undefined" && props.islands) props.islands.forEach(function (island) { hide(island.h); });
    if (typeof cloudSea !== "undefined") hide(cloudSea);
    if (typeof puffMat !== "undefined") scene.children.forEach(function (node) { if (node.material === puffMat) hide(node); });
    if (typeof fallMat !== "undefined") scene.children.forEach(function (node) { if (node.material === fallMat) hide(node); });
    if (typeof camera !== "undefined") camera.layers.disable(2);
  }
  function tycoonParkFrame(dt) {
    if (!TYCOON_PARK_STATE.group || !TYCOON_PARK_STATE.group.visible) return;
    TYCOON_PARK_STATE.upgrades.forEach(function (mesh) {
      if (!mesh.visible || mesh.userData.growth >= 1) return;
      const u = Math.min(1, (mesh.userData.growth || 0) + Math.max(0, Math.min(.1, dt || 0)) / .7);
      mesh.userData.growth = u; mesh.scale.y = Math.max(.01, u * u * (3 - 2 * u)); mesh.updateMatrix();
    });
    // Permanent soft daylight is the park's art direction, not a market/weather indicator. The original camera
    // tour still has its day/night cycle. No business state is inferred from this decorative lighting palette.
    tycoonParkHideLegacy(true);
    if (typeof hemi !== "undefined") {
      hemi.color.set(0xd5eeff); hemi.groundColor.set(0x8aa374); hemi.intensity = 1.4;
      sun.color.set(0xfff1d6); sun.intensity = 1.85;
      sun.position.copy(cam.look).addScaledVector(TYCOON_DAY_DIRECTION, 60);
      if (sun.target) sun.target.position.copy(cam.look);
      renderer.toneMappingExposure = 1.03;
    }
    if (typeof skyU !== "undefined") {
      skyU.uTop.value.set(0x72bce9); skyU.uMid.value.set(0xb7def4); skyU.uHorizon.value.set(0xe3eddf);
      skyU.uBelow.value.set(0x91c5df); skyU.uSunCol.value.set(0xfff2d7); skyU.uStars.value = 0;
      skyU.uSunDir.value.copy(TYCOON_DAY_DIRECTION);
      cloudU.uLit.value.set(0xe7f2f4); cloudU.uShade.value.set(0xa8c4d0); cloudU.uFar.value.set(0xdcebdc);
      cloudU.uSunDir.value.copy(TYCOON_DAY_DIRECTION); scene.fog.color.set(0xdcebdc);
    }
  }
  function tycoonParkPick(clientX, clientY) {
    if (!TYCOON_PARK_STATE.group || !TYCOON_PARK_STATE.group.visible) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    if (!rect.width || !rect.height || clientX < rect.left || clientY < rect.top
        || clientX > rect.right || clientY > rect.bottom) return null;
    const ray = new THREE.Raycaster(), point = new THREE.Vector3(), local = new THREE.Vector3();
    ray.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1,
      -(clientY - rect.top) / rect.height * 2 + 1), camera);
    const extents = { table: [6.1, 6.1], workshop: [4.2, 4.65], den: [4.2, 4.65],
      archive: [4.0, 4.35], vault: [4.0, 4.35], observatory: [5.7, 5.7], dock: [3.1, 2.1] };
    const crew = { table: "voss", workshop: "pip", den: "nyx", archive: "mote", vault: "rook", dock: "jet" };
    let closest = Infinity, chosen = null;
    Object.keys(extents).forEach(function (room) {
      const frame = RF[room], origin = frame ? frame.origin : new THREE.Vector3(room === "dock" ? 23.2 : 0, 0, room === "dock" ? -1.5 : 0);
      if (!ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -origin.y), point)) return;
      local.copy(point).sub(origin).applyAxisAngle(new THREE.Vector3(0, 1, 0), frame ? -frame.yaw : 0);
      const size = extents[room], inside = room === "table" || room === "observatory"
        ? Math.hypot(local.x, local.z) <= size[0] : Math.abs(local.x) <= size[0] && Math.abs(local.z) <= size[1];
      const distance = ray.ray.origin.distanceTo(point);
      if (inside && distance < closest) { closest = distance; chosen = crew[room] || room; }
    });
    return chosen;
  }
  function tycoonPark(on) {
    if (!TYCOON_PARK_STATE.group && !on) return;
    const group = TYCOON_PARK_STATE.group || tycoonParkBuild(); group.visible = !!on;
    tycoonParkHideLegacy(!!on);
  }
  function tycoonParkState() {
    const group = TYCOON_PARK_STATE.group;
    return { on: !!(group && group.visible), meshes: group ? group.children.length : 0,
      departments: TYCOON_PARK_STATE.departments.slice(), paths: TYCOON_PARK_STATE.routes.length,
      growth: Object.assign({}, TYCOON_PARK_STATE.growth), earnedGardens: TYCOON_PARK_STATE.upgrades.filter(function (m) { return m.visible; }).length };
  }
  if (typeof BUS !== "undefined") BUS.on("frame", tycoonParkFrame);
"""
