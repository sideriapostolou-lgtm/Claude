"""A landscaped toy town over the existing set; all business activity remains ledger driven."""

TYCOON_PARK = r"""
  // Colour identifies a department, never a simulated flow of money. The same cast, feet, desk coordinates
  // and walking graph survive the park treatment. Decorative buildings cannot send an order or invent work.
  const TYCOON_PARK_COLORS = { table: 0x08afa7, workshop: 0xff8c22, den: 0x9955e8,
    vault: 0x258ae8, archive: 0x20b778, dock: 0xffbf26, observatory: 0x526ee6 };
  const TYCOON_PARK_STATE = { group: null, routes: [], departments: [], flags: [], upgrades: [],
    growth: { qualified: false, level: null, pnl_usd: null }, hidden: [], hiddenSet: new Set() };
  const TYCOON_DAY_DIRECTION = new THREE.Vector3(-.45, .85, .4).normalize();

  function tycoonParkBuild() {
    const group = new THREE.Group(); group.name = "tycoon:park";
    const ground = [], signs = [], landscape = [], buildings = [], white = 0xf9fcff, paving = 0xdfe6ed;
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
      disc(1.05 * size, 0x36ad43, v(x + .18 * size, -.139, z + .12 * size));
      box(landscape, .31 * size, 1.95 * size, .31 * size, 0x996337, v(x, .83 * size, z));
      // Three clean plastic blocks read as a tree at phone size; no noisy leaf textures or extra draw calls.
      box(landscape, 1.85 * size, 1.48 * size, 1.72 * size, 0x2cba50, v(x, 2.07 * size, z));
      box(landscape, 1.38 * size, .72 * size, 1.28 * size, 0x55d862, v(x - .12 * size, 3.04 * size, z - .04 * size));
      box(landscape, .72 * size, .82 * size, 1.08 * size, 0x22a546, v(x + .80 * size, 1.94 * size, z + .14 * size));
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
      box(signs, .14, 2.65, .14, white, at(0, 1.325, 0), yaw);
      box(signs, .22, .22, .22, colour, at(0, 2.77, 0), yaw);
      box(signs, 1.18, .73, .13, colour, at(.49, 2.25, 0), yaw);
      box(signs, .18, .74, .15, white, at(.20, 2.25, 0), yaw);
      TYCOON_PARK_STATE.flags.push({ room: room, position: point.toArray() });
    };
    const emblem = function (frame, room, colour, x, y, z, size) {
      const at = function (a, b, c) { return frame.at(x + a * size, y + b * size, z + c * size); };
      const block = function (w, h, d, tint, a, b, c, tilt) {
        const geometry = new THREE.BoxGeometry(w * size, h * size, d * size);
        if (tilt) geometry.rotateZ(tilt);
        put(signs, geometry, tint, at(a, b, c), frame.yaw);
      };
      const ring = function (radius, tube, a, b, c) {
        put(signs, new THREE.TorusGeometry(radius * size, tube * size, 6, 16), white, at(a, b, c), frame.yaw);
      };
      block(1.86, 1.64, .20, white, 0, 0, 0);
      block(1.66, 1.44, .24, colour, 0, 0, .035);
      if (room === "workshop") {
        ring(.36, .105, -.13, .10, .23);
        block(.16, .58, .12, white, .30, -.31, .23, Math.PI / 4);
      } else if (room === "den") {
        put(signs, new THREE.CylinderGeometry(.56 * size, .56 * size, .14 * size, 5).rotateX(Math.PI / 2),
          white, at(0, .04, .22), frame.yaw);
        block(.13, .36, .14, colour, -.12, -.05, .32, Math.PI / 4);
        block(.13, .62, .14, colour, .12, .04, .32, -Math.PI / 4);
      } else if (room === "vault") {
        ring(.25, .075, 0, .25, .22);
        block(.70, .54, .13, white, 0, -.13, .25);
        block(.09, .21, .15, colour, 0, -.12, .33);
      } else if (room === "archive") {
        [-.31, 0, .31].forEach(function (offset, i) {
          block(.96 - i * .09, .20, .15, white, i % 2 * .06, offset, .22);
          block(.10, .22, .18, colour, -.23, offset, .24);
        });
      } else if (room === "dock") {
        block(.90, .85, .16, white, 0, 0, .22);
        block(.14, .88, .18, colour, 0, 0, .25);
        block(.90, .13, .18, colour, 0, .13, .26);
      } else {
        block(.18, .98, .14, white, 0, 0, .22, Math.PI / 4);
        block(.18, .98, .14, white, 0, 0, .23, -Math.PI / 4);
        block(.26, .26, .16, colour, 0, 0, .32);
      }
    };

    // A connected lawn replaces the visual gaps between floating islets. It stays below every original floor,
    // foot and contact shadow. Alternating mowing strips are decorative, not lots for sale or profit counters.
    box(landscape, 56, 3.0, 50, 0x9d7251, v(2, -1.65, -3));
    box(landscape, 56.2, .24, 50.2, 0x37a749, v(2, -.27, -3));
    for (let row = 0; row < 10; row++) for (let column = 0; column < 12; column++) {
      rectangle(56 / 12 + .002, 5.002, (row + column) % 2 ? 0x55c747 : 0x60d14c,
        v(-26 + (column + .5) * 56 / 12, -.145, -28 + (row + .5) * 5));
    }
    DISCS.forEach(function (d, i) {
      disc(d[2] - .09, i % 3 === 0 ? 0x60d14c : i % 3 === 1 ? 0x55c747 : 0x66d653,
        v(d[0], d[3] + .002 - i * .00003, d[1]));
    });
    disc(COURT_R + .44, 0x3fa746, v(0, .007, 0));
    disc(COURT_R + .18, paving, v(0, .008, 0));
    put(ground, new THREE.RingGeometry(COURT_R - .12, COURT_R + .12, 80).rotateX(-Math.PI / 2),
      TYCOON_PARK_COLORS.table, v(0, .009, 0));
    put(ground, new THREE.RingGeometry(2.42, 2.53, 64).rotateX(-Math.PI / 2),
      TYCOON_PARK_COLORS.table, v(0, .009, 0));
    rectangle(4.8, 8.4, white, v(0, -.12, 17.7));
    rectangle(4.35, 8.4, paving, v(0, -.11, 17.7));
    rectangle(32.6, 2.60, white, v(4, .009, 16.2));
    rectangle(32.6, 2.24, paving, v(4, .010, 16.2));

    // Open-front toy shops: a thick sign wall, colored side plinths and a generous striped canopy make the
    // department recognizable before its text label is readable. The work area stays open to the camera.
    const dimensions = { workshop: [7.5, 7], den: [7.5, 7], archive: [7, 6.4], vault: [7, 6.4] };
    Object.keys(ROOMS).forEach(function (key) {
      const frame = RF[key], colour = TYCOON_PARK_COLORS[key], size = dimensions[key];
      if (colour == null) return;
      TYCOON_PARK_STATE.departments.push(key);
      if (frame && size) {
        const pale = new THREE.Color(colour).lerp(new THREE.Color(white), .48),
          dark = new THREE.Color(colour).multiplyScalar(.55), w = size[0], d = size[1];
        rectangle(w + 1.14, d + 1.10, 0x3ca448, frame.at(.12, .003, -.05), frame.yaw);
        rectangle(w + .74, d + .74, colour, frame.at(0, .004, 0), frame.yaw);
        rectangle(w - .03, d - .03, white, frame.at(0, .006, 0), frame.yaw);
        rectangle(4.9, 2.20, white, frame.at(0, .008, d / 2 + .7), frame.yaw);
        rectangle(4.6, 1.92, colour, frame.at(0, .009, d / 2 + .7), frame.yaw);
        rectangle(2.02, 1.96, paving, frame.at(0, .010, d / 2 + .7), frame.yaw);
        badge(frame.at(-2.65, 0, d / 2 + .9), frame.yaw, colour, key);
        // The tall silhouette is at the rear, away from every doorway, desk and worker home.
        if (key === "den") {
          // The overview sees Nyx from this shop's rear. A wide, open cutaway keeps her real home visible;
          // the outer towers and roof trim preserve the building silhouette without a wall across her face.
          [-1, 1].forEach(function (sign) {
            box(buildings, 2.08, 2.34, .56, pale, frame.at(sign * (w / 2 - .76), 1.17, -d / 2), frame.yaw);
          });
          box(buildings, w - 3.52, .73, .56, pale, frame.at(0, .365, -d / 2), frame.yaw);
        } else box(buildings, w + .56, 2.34, .56, pale, frame.at(0, 1.17, -d / 2), frame.yaw);
        box(buildings, w + .58, .64, .60, colour, frame.at(0, .35, -d / 2), frame.yaw);
        const roofEdge = function (width, height, depth, tint, y, z) {
          if (key === "den") [-1, 1].forEach(function (sign) {
            box(buildings, 2.20, height, depth, tint, frame.at(sign * (w / 2 - .57), y, z), frame.yaw);
          });
          else box(buildings, width, height, depth, tint, frame.at(0, y, z), frame.yaw);
        };
        // Nyx's low body also needs an opening through the rear roof trim when viewed from a small phone.
        // Two roof towers frame her workspace; a continuous beam here would cross the selected-camera ray.
        roofEdge(w + 1.02, .45, 1.25, colour, 2.53, -d / 2);
        roofEdge(w + 1.14, .14, 1.36, white, 2.83, -d / 2);
        roofEdge(w + .70, .12, .76, dark, 2.29, -d / 2 + .20);
        emblem(frame, key, colour, key === "den" ? 3.0 : 0, 3.32, -d / 2 + .38, .92);
        [-1, 1].forEach(function (sign) {
          const x = sign * (key === "den" ? 2.85 : 2.23);
          box(buildings, 1.52, 1.07, .10, colour, frame.at(x, 1.45, -d / 2 + .34), frame.yaw);
          box(buildings, 1.25, .81, .12, 0x243f62, frame.at(x, 1.45, -d / 2 + .41), frame.yaw);
          box(buildings, .10, .84, .14, white, frame.at(x, 1.45, -d / 2 + .47), frame.yaw);
          box(buildings, 1.28, .10, .14, white, frame.at(x, 1.45, -d / 2 + .47), frame.yaw);
        });
        [-1, 1].forEach(function (sign) {
          box(buildings, .39, 2.90, .40, colour, frame.at(sign * (w / 2 + .04), 1.45, -d / 2), frame.yaw);
          box(buildings, .59, .21, d - .12, colour, frame.at(sign * w / 2, .87, 0), frame.yaw);
          box(buildings, .26, 2.56, .26, white, frame.at(sign * 1.88, 1.28, d / 2 + 1.24), frame.yaw);
          box(buildings, .41, .37, .41, dark, frame.at(sign * 1.88, .18, d / 2 + 1.24), frame.yaw);
        });
        for (let stripe = 0; stripe < 10; stripe++) {
          const x = (stripe - 4.5) * .44, shade = stripe % 2 ? white : colour;
          box(buildings, .442, .24, 1.82, shade, frame.at(x, 2.65, d / 2 + .58), frame.yaw);
          box(buildings, .442, .31, .17, shade, frame.at(x, 2.46, d / 2 + 1.49), frame.yaw);
        }
        // Small department-colour planter boxes finish the corners without surrounding the worker in labels.
        [-1, 1].forEach(function (sign) {
          box(buildings, 1.02, .43, .72, white, frame.at(sign * (w / 2 - .62), .22, d / 2 + .72), frame.yaw);
          box(buildings, .87, .12, .58, dark, frame.at(sign * (w / 2 - .62), .44, d / 2 + .72), frame.yaw);
          box(buildings, .82, .57, .61, 0x23b754, frame.at(sign * (w / 2 - .62), .74, d / 2 + .72), frame.yaw);
          box(buildings, .20, .21, .19, key === "den" ? 0xffbc35 : 0xff638d,
            frame.at(sign * (w / 2 - .62), 1.10, d / 2 + .72), frame.yaw);
        });
      } else if (key === "observatory" && frame) {
        disc(5.73, 0x3ca448, frame.at(0, .004, 0));
        disc(5.48, paving, frame.at(0, .006, 0));
        put(ground, new THREE.RingGeometry(4.91, 5.43, 64).rotateX(-Math.PI / 2), colour, frame.at(0, .008, 0));
        // A low octagonal science terrace replaces the opaque-looking glass greenhouse in town mode.
        // Its front stays entirely open to the existing stairs and observation desk.
        for (let i = 0; i < 7; i++) {
          const angle = Math.PI * (.5 + i / 6), x = Math.sin(angle) * 5.47, z = Math.cos(angle) * 5.47;
          const yaw = frame.yaw + angle;
          box(buildings, 3.25, .92, .38, white, frame.at(x, .46, z), yaw);
          box(buildings, 3.42, .20, .61, colour, frame.at(x, 1.03, z), yaw);
        }
        box(buildings, 7.0, .56, 1.04, colour, frame.at(0, 2.43, -5.1));
        box(buildings, 7.18, .16, 1.19, white, frame.at(0, 2.79, -5.1));
        [-2.8, 2.8].forEach(function (x) { box(buildings, .41, 2.61, .44, colour, frame.at(x, 1.30, -5.1)); });
        emblem(frame, key, colour, 0, 3.24, -4.83, 1.05);
        badge(frame.at(-2.15, 0, 4.95), frame.yaw, colour, key);
      } else if (key === "dock") {
        rectangle(5.08, 2.55, 0x3ca448, v(23.2, .007, -1.5));
        rectangle(4.75, 2.22, paving, v(23.2, .009, -1.5));
        rectangle(4.75, .18, colour, v(23.2, .010, -2.5));
        rectangle(4.75, .18, colour, v(23.2, .010, -.5));
        badge(v(24.95, 0, -2.37), 0, colour, key);
        // The parcel depot sits behind Jet, clear of his console and the walkway at x=19.5.
        box(buildings, .52, 2.55, 3.12, white, v(25.81, 1.27, -1.5));
        box(buildings, 1.10, .38, 3.56, colour, v(25.74, 2.63, -1.5));
        box(buildings, 1.19, .12, 3.69, white, v(25.74, 2.89, -1.5));
        emblem({ at: function (x, y, z) { return v(25.48 - z, y, -1.5 + x); }, yaw: -Math.PI / 2 },
          key, colour, 0, 3.34, 0, .88);
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
        midpoint.y += .0111; rectangle(1.76, length + .11, white, midpoint, yaw);
        midpoint.y += .0004; rectangle(1.49, length + .04, paving, midpoint, yaw);
        TYCOON_PARK_STATE.routes.push([key, other]);
      });
    });
    [-23, -19, -15, -11, -7, 7, 11, 15, 19, 23, 27].forEach(function (x, i) { tree(x, -24 + i % 2, .95 + i % 3 * .15); });
    [-18, -12, -6, 0, 6, 12, 17].forEach(function (z, i) { tree(-23, z, 1 + i % 2 * .22); });
    [-18, -12, 7, 13, 18].forEach(function (z, i) { tree(27, z, .96 + i % 2 * .18); });
    fence(-23.2, -3, 44, Math.PI / 2); fence(27.6, -3, 44, Math.PI / 2);
    fence(2, -25.2, 50.4, 0); fence(-12.4, 19.3, 19.6, 0); fence(14.4, 19.3, 23.6, 0);
    [-1, 1].forEach(function (sign) {
      box(buildings, .92, 3.90, .95, 0x196ec7, v(sign * 2.55, 1.81, 19.3));
      box(buildings, 1.17, .42, 1.20, white, v(sign * 2.55, .13, 19.3));
      box(buildings, 1.14, .25, 1.20, 0xffcb39, v(sign * 2.55, 3.88, 19.3));
      box(buildings, .34, .40, .34, white, v(sign * 2.55, 4.20, 19.3));
      // Fixed pennants are decoration, with no visitor count, ticket price or earnings claim.
      box(signs, .11, 1.63, .11, white, v(sign * 3.30, 4.07, 19.3));
      box(signs, .94, .56, .12, sign < 0 ? 0xff8d32 : 0x9955e8, v(sign * 3.68, 4.55, 19.3));
    });
    box(buildings, 6.16, .95, .76, 0x196ec7, v(0, 3.82, 19.3));
    box(buildings, 6.42, .19, 1.02, white, v(0, 4.39, 19.3));
    box(signs, 2.05, .48, .12, white, v(0, 3.84, 19.75));
    [-.54, 0, .54].forEach(function (x) { box(signs, .28, .28, .14, TYCOON_PARK_COLORS.table, v(x, 3.84, 19.83)); });
    [-18, -8, 9, 18].forEach(function (x) {
      box(landscape, 2.05, .18, .65, 0xffa735, v(x, .56, 18.05));
      box(landscape, 2.05, .65, .15, 0xffa735, v(x, .96, 18.30));
      [-.69, .69].forEach(function (offset) { box(landscape, .14, .54, .50, 0x294d74, v(x + offset, .24, 18.05)); });
      box(landscape, .63, .96, .63, 0x258ae8, v(x + 1.68, .34, 18.10));
      box(landscape, .70, .13, .70, 0x294d74, v(x + 1.68, .88, 18.10));
    });

    const merge = function (list, name, cast, parent) {
      const geometry = mergeGeometries(list, false); if (!geometry) return null;
      const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: cast ? .62 : .88,
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
      hemi.color.set(0xd5eeff); hemi.groundColor.set(0x749960); hemi.intensity = .82;
      sun.color.set(0xfff5e6); sun.intensity = 1.55;
      sun.position.copy(cam.look).addScaledVector(TYCOON_DAY_DIRECTION, 60);
      if (sun.target) sun.target.position.copy(cam.look);
      renderer.toneMappingExposure = .94;
    }
    if (typeof skyU !== "undefined") {
      skyU.uTop.value.set(0x258cdc); skyU.uMid.value.set(0x75c3f6); skyU.uHorizon.value.set(0xb1e3ff);
      skyU.uBelow.value.set(0x65b9eb); skyU.uSunCol.value.set(0xfff5e6); skyU.uStars.value = 0;
      skyU.uSunDir.value.copy(TYCOON_DAY_DIRECTION);
      cloudU.uLit.value.set(0xf5fbff); cloudU.uShade.value.set(0x9cbfe0); cloudU.uFar.value.set(0xb1e3ff);
      cloudU.uSunDir.value.copy(TYCOON_DAY_DIRECTION); scene.fog.color.set(0xb1e3ff);
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
