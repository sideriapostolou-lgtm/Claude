"""A landscaped toy town over the existing set; all business activity remains ledger driven."""

TYCOON_PARK = r"""
  // Colour identifies a department, never a simulated flow of money. The same cast, feet, desk coordinates
  // and walking graph survive the park treatment. Decorative buildings cannot send an order or invent work.
  const TYCOON_PARK_COLORS = { table: 0x45d8ca, workshop: 0x6c9fc4, den: 0xb77aa5,
    vault: 0x6bbfd2, archive: 0x4cb7a0, dock: 0x65c6ca, observatory: 0x739ace };
  const TYCOON_PARK_STATE = { group: null, routes: [], departments: [], flags: [], upgrades: [],
    growth: { qualified: false, level: null, pnl_usd: null }, hidden: [], hiddenSet: new Set() };
  const TYCOON_DAY_DIRECTION = new THREE.Vector3(-.45, .85, .4).normalize();

  function tycoonParkBuild() {
    const group = new THREE.Group(); group.name = "tycoon:park";
    const ground = [], signs = [], landscape = [], buildings = [], white = 0x9dbbc8, paving = 0x304b60;
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
    const badge = function (point, yaw, colour, room) {
      const at = function (x, y, z) { return v(x, y, z).applyAxisAngle(v(0, 1, 0), yaw).add(point); };
      box(signs, .14, 2.65, .14, white, at(0, 1.325, 0), yaw);
      box(signs, .22, .22, .22, colour, at(0, 2.77, 0), yaw);
      box(signs, 1.18, .73, .13, colour, at(.49, 2.25, 0), yaw);
      box(signs, .18, .74, .15, white, at(.20, 2.25, 0), yaw);
      TYCOON_PARK_STATE.flags.push({ room: room, position: point.toArray() });
    };
    // Architectural campus, not a simulated city economy. The complete floor is connected and
    // all pathways follow real navigation. No moving particles, invented visitors or order streams.
    box(landscape, 56, 2.3, 50, 0x0b1728, v(2, -1.30, -3));
    box(landscape, 56.2, .16, 50.2, 0x233a50, v(2, -.23, -3));
    rectangle(56.2, 50.2, 0x182a3c, v(2, -.145, -3));
    // A quiet unpatterned campus surface keeps the actual workplaces legible at phone scale.
    DISCS.forEach(function (d, i) {
      disc(d[2] - .09, 0x344c5f, v(d[0], d[3] + .002 - i * .00003, d[1]));
    });
    disc(COURT_R + .44, 0x102336, v(0, .007, 0));
    disc(COURT_R + .18, 0x446175, v(0, .008, 0));
    put(ground, new THREE.RingGeometry(COURT_R - .12, COURT_R + .12, 80).rotateX(-Math.PI / 2),
      TYCOON_PARK_COLORS.table, v(0, .009, 0));


    // Generous low cutaway laboratories. The upper frame sits at the rear; the workstation,
    // resident and doorway remain visible from either phone overview or selected camera.
    const dimensions = { workshop: [7.5, 7], den: [7.5, 7], archive: [7, 6.4], vault: [7, 6.4] };
    Object.keys(ROOMS).forEach(function (key) {
      const frame = RF[key], colour = TYCOON_PARK_COLORS[key], size = dimensions[key];
      if (colour == null) return;
      TYCOON_PARK_STATE.departments.push(key);
      if (frame && size) {
        const w = size[0], d = size[1], shell = 0x627d8d, edge = 0x98b5bf;
        rectangle(w + .74, d + .74, colour, frame.at(0, .004, 0), frame.yaw);
        rectangle(w + .54, d + .54, 0x152a3f, frame.at(0, .005, 0), frame.yaw);
        rectangle(w - .03, d - .03, 0x76929d, frame.at(0, .006, 0), frame.yaw);
        rectangle(2.35, 2.20, colour, frame.at(0, .008, d / 2 + .7), frame.yaw);
        rectangle(2.02, 2.20, paving, frame.at(0, .009, d / 2 + .7), frame.yaw);
        badge(frame.at(-2.65, 0, d / 2 + .9), frame.yaw, colour, key);
        [-1, 1].forEach(function (sign) {
          // Rear corner towers leave a central sightline, including the short practice resident.
          box(buildings, 1.22, 2.80, .64, shell, frame.at(sign * (w / 2 - .35), 1.40, -d / 2), frame.yaw);
          // Solid corner volumes and partial roofs read as finished cutaway laboratories.
          box(buildings, 1.70, 1.85, .46, shell, frame.at(sign * (w / 2 - .60), .925, -d / 2), frame.yaw);
          box(buildings, 1.75, .24, 2.10, shell, frame.at(sign * (w / 2 - .60), 2.90, -d / 2 + .68), frame.yaw);
          box(buildings, 1.77, .055, 2.12, edge, frame.at(sign * (w / 2 - .60), 3.05, -d / 2 + .68), frame.yaw);

          box(buildings, .09, 2.45, .69, colour, frame.at(sign * (w / 2 - .35), 1.43, -d / 2 + .04), frame.yaw);
          box(buildings, .48, .85, d, shell, frame.at(sign * w / 2, .425, 0), frame.yaw);
          box(buildings, .54, .10, d, edge, frame.at(sign * w / 2, .90, 0), frame.yaw);
          box(buildings, 1.08, .48, .84, shell, frame.at(sign * (w / 2 - .55), .24, d / 2 + .50), frame.yaw);
          box(buildings, .88, .15, .66, 0x275c59, frame.at(sign * (w / 2 - .55), .52, d / 2 + .50), frame.yaw);
          put(buildings, new THREE.IcosahedronGeometry(.42, 1), 0x469786,
            frame.at(sign * (w / 2 - .55), .86, d / 2 + .50));
        });
        box(buildings, w + .55, .22, .94, shell, frame.at(0, 2.92, -d / 2), frame.yaw);
        box(buildings, w + .55, .055, .98, colour, frame.at(0, 3.06, -d / 2), frame.yaw);
        // A low rear equipment wall is kept below faces, with static vents instead of fake charts.
        box(buildings, w - 2.0, .68, .44, shell, frame.at(0, .34, -d / 2), frame.yaw);
        for (let i = -2; i <= 2; i++) {
          box(buildings, .46, .045, .07, edge, frame.at(i * .72, .45, -d / 2 + .24), frame.yaw);
        }
      } else if (key === "observatory" && frame) {
        disc(5.73, 0x102336, frame.at(0, .004, 0));
        disc(5.48, 0x627f90, frame.at(0, .006, 0));
        put(ground, new THREE.RingGeometry(5.30, 5.43, 64).rotateX(-Math.PI / 2), colour, frame.at(0, .008, 0));
        for (let i = 0; i < 7; i++) {
          const angle = Math.PI * (.5 + i / 6), x = Math.sin(angle) * 5.47, z = Math.cos(angle) * 5.47;
          box(buildings, 3.25, .58, .38, 0x243e56, frame.at(x, .29, z), frame.yaw + angle);
          box(buildings, 3.28, .06, .42, colour, frame.at(x, .61, z), frame.yaw + angle);
        }
        [-2.8, 2.8].forEach(function (x) {
          box(buildings, .32, 2.9, .44, 0x243e56, frame.at(x, 1.45, -5.1));
          box(buildings, .08, 2.5, .46, colour, frame.at(x, 1.45, -5.08));
        });
        box(buildings, 7.0, .22, .80, 0x243e56, frame.at(0, 3.0, -5.1));
        box(buildings, 7.0, .05, .84, colour, frame.at(0, 3.15, -5.1));
        badge(frame.at(-2.15, 0, 4.95), frame.yaw, colour, key);
      } else if (key === "dock") {
        rectangle(5.08, 2.55, colour, v(23.2, .007, -1.5));
        rectangle(4.85, 2.32, paving, v(23.2, .009, -1.5));
        badge(v(24.95, 0, -2.37), 0, colour, key);
        box(buildings, .52, 2.55, 3.12, 0x243e56, v(25.81, 1.27, -1.5));
        box(buildings, .56, .07, 3.18, colour, v(25.81, 2.59, -1.5));
        [-2.45, -.55].forEach(function (z) {
          box(buildings, .04, 1.8, .06, colour, v(25.52, 1.3, z));
        });
      }
    });
    Object.keys(NAV).forEach(function (key) {
      NAV[key].edges.forEach(function (other) {
        if (key >= other || key.startsWith("tb") || other.startsWith("tb")) return;
        const a = NAV[key].p, b = NAV[other].p;
        if (Math.abs(a.y - b.y) > .05) return;
        const length = a.distanceTo(b); if (length < .05) return;
        TYCOON_PARK_STATE.routes.push([key, other]);
      });
    });
    // Four broad primary approaches replace the detailed navigation mesh. Navigation keeps
    // every original node, but the drawing is a calm, readable campus rather than a wireframe.
    [[200, RF.workshop.at(0, 0, 4)], [340, RF.den.at(0, 0, 4)],
      [135, RF.archive.at(0, 0, 3.7)], [45, RF.vault.at(0, 0, 3.7)]].forEach(function (q) {
      const angle = q[0] * Math.PI / 180, a = v(Math.cos(angle) * COURT_R, .010, Math.sin(angle) * COURT_R),
        b = q[1], midpoint = a.clone().add(b).multiplyScalar(.5), yaw = Math.atan2(b.x - a.x, b.z - a.z);
      midpoint.y = .010; rectangle(2.8, a.distanceTo(b) + .6, 0x526d7e, midpoint, yaw);
    });
    // A single broad service promenade reaches the order workstation; no secondary edge network.
    rectangle(18.8, 2.8, 0x526d7e, v(13.2, .010, 2));
    rectangle(2.8, 4.5, 0x526d7e, v(22.6, .010, .25));
    for (let i = 0; i < 10; i++) {
      const zf = -6.2 - .25 * i, depth = zf + 8.8;
      box(buildings, 3.2, .18 * (i + 1), depth, 0x304b60,
        v(0, .09 * (i + 1), zf - depth / 2));
      box(buildings, 3.2, .018, .045, 0x528c99, v(0, .18 * (i + 1) + .009, zf - .02));
    }
    // Sparse architectural landscaping frames the campus; all foliage is static decoration.
    [-20, -13, -6, 8, 15, 23].forEach(function (x) {
      box(landscape, 2.6, .4, 1.5, 0x294459, v(x, .05, -23));
      [-.7, .7].forEach(function (dx) {
        put(landscape, new THREE.IcosahedronGeometry(.85, 1), 0x3e8a7b, v(x + dx, .96, -23));
      });
    });
    // Restrained perimeter light strips are fixed architectural details, unrelated to desk state.
    [-25.6, 29.6].forEach(function (x) {
      box(landscape, .14, .22, 49.5, 0x3e7c86, v(x, -.05, -3));
    });
    box(landscape, 55, .22, .14, 0x3e7c86, v(2, -.05, -27.6));

    const merge = function (list, name, cast, parent) {
      const geometry = mergeGeometries(list, false); if (!geometry) return null;
      const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: cast ? .48 : .78,
        metalness: cast ? .24 : .08, depthWrite: !!cast, polygonOffset: !cast, polygonOffsetFactor: 0, polygonOffsetUnits: -1 });
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
    // Replace the previous fantasy architecture completely, retaining actor parents, lights,
    // receipt objects and all navigation. Layer masks restore the original tour exactly.
    if (typeof staticMeshes !== "undefined") staticMeshes.forEach(hide);
    if (typeof TY_CUTAWAY !== "undefined") TY_CUTAWAY.parts.forEach(function (part) {
      hide(part.cover); hide(part.low);
    });
    if (typeof STANDIN !== "undefined") Object.values(STANDIN).forEach(function (list) {
      if (Array.isArray(list)) list.forEach(hide);
    });
    if (typeof props !== "undefined") Object.values(props).forEach(hide);
    if (typeof MAT !== "undefined") scene.children.forEach(function (node) {
      if (node.isInstancedMesh && [MAT.leaf, MAT.books, MAT.brass].includes(node.material)) hide(node);
    });
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
    // These older signs describe Polymarket limits and the shared legacy ledger.
    // Kalshi safeguards and receipts live in its workstation and Money details.
    if (typeof recWall !== "undefined") hide(recWall);
    if (typeof recPlaque !== "undefined") hide(recPlaque);
    if (typeof props !== "undefined" && props.islands) props.islands.forEach(function (island) { hide(island.h); });
    // Jet's actual workstation remains at the parcel depot. This older decorative aircraft and gangway do
    // not represent an order, holding or delivery, so remove them from the phone town with reversible layers.
    if (typeof props !== "undefined") { hide(props.airship); hide(props.airshipModel); }
    if (typeof STANDIN !== "undefined" && STANDIN.airship) STANDIN.airship.forEach(hide);
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
    // The cinema's camera-following key and bright room lamps are night-set decoration. In daylight they
    // bleach the cast. Keep only a small accent; business status-lamp colors and event lights are untouched.
    if (typeof keyLight !== "undefined") keyLight.intensity = 0;
    if (typeof practicals !== "undefined") Object.values(practicals).forEach(function (p) { p.light.intensity = p.base * .10; });
    if (typeof hemi !== "undefined") {
      hemi.color.set(0xd5eeff); hemi.groundColor.set(0x38546a); hemi.intensity = 1.15;
      sun.color.set(0xfff5e6); sun.intensity = 2.0;
      sun.position.copy(cam.look).addScaledVector(TYCOON_DAY_DIRECTION, 60);
      if (sun.target) sun.target.position.copy(cam.look);
      renderer.toneMappingExposure = 1.04;
    }
    if (typeof skyU !== "undefined") {
      skyU.uTop.value.set(0x172d46); skyU.uMid.value.set(0x34566f); skyU.uHorizon.value.set(0x668699);
      skyU.uBelow.value.set(0x314a61); skyU.uSunCol.value.set(0xfff5e6); skyU.uStars.value = 0;
      skyU.uSunDir.value.copy(TYCOON_DAY_DIRECTION);
      cloudU.uLit.value.set(0xf5fbff); cloudU.uShade.value.set(0x9cbfe0); cloudU.uFar.value.set(0x668699);
      cloudU.uSunDir.value.copy(TYCOON_DAY_DIRECTION); scene.fog.color.set(0x668699);
      // The overview can be 150m from the set on a narrow phone. Fog must not bleach the entire park.
      scene.fog.near = 180; scene.fog.far = 520;
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
