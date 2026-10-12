"""An optional landscaped skin for the existing town; no business state or movement."""

TYCOON_PARK = r"""
  // Department colours identify places, never profit or a simulated flow of money.
  const TYCOON_PARK_COLORS = { table: 0x4cbcb4, workshop: 0xf0a15f, den: 0xad8ae8,
    vault: 0x72b4dc, archive: 0x77cba3, dock: 0xeac452, observatory: 0x889fe7 };
  const TYCOON_PARK_STATE = { group: null, routes: [], departments: [], flags: [] };

  function tycoonParkBuild() {
    const group = new THREE.Group(); group.name = "tycoon:park";
    const ground = [], signs = [], white = 0xfff5dc, paving = 0xf1e2bd;
    const put = function (list, geo, colour, point, yaw) {
      if (yaw) geo.rotateY(yaw);
      if (point) geo.translate(point.x, point.y, point.z);
      paint(geo, colour); list.push(prep(geo));
    };
    const disc = function (radius, colour, point) {
      put(ground, new THREE.CircleGeometry(radius, 64).rotateX(-Math.PI / 2), colour, point);
    };
    const rectangle = function (width, depth, colour, point, yaw) {
      put(ground, new THREE.PlaneGeometry(width, depth).rotateX(-Math.PI / 2), colour, point, yaw);
    };
    const badge = function (point, yaw, colour, room) {
      // Low pennants sit beside entrances, away from the route, lamps and the existing flower arches.
      const at = function (x, y, z) { return new THREE.Vector3(x, y, z).applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw).add(point); };
      put(signs, new THREE.CylinderGeometry(0.035, 0.05, 2.65, 8), white, at(0, 1.325, 0));
      put(signs, new THREE.SphereGeometry(0.075, 8, 6), colour, at(0, 2.71, 0));
      put(signs, new THREE.BoxGeometry(0.85, 0.62, 0.055), colour, at(0.4, 2.26, 0), yaw);
      put(signs, new THREE.BoxGeometry(0.11, 0.62, 0.065), white, at(0.15, 2.26, 0), yaw);
      TYCOON_PARK_STATE.flags.push({ room: room, position: point.toArray() });
    };

    // The original island outlines and raised observatory stay exactly where they are. Millimetre-thin skins
    // leave feet and their contact shadows above the ground; the original rugs and furniture remain visible.
    DISCS.forEach(function (d, i) {
      disc(d[2] - 0.09, i % 3 === 0 ? 0x83b965 : i % 3 === 1 ? 0x79af5c : 0x90bd6b,
        new THREE.Vector3(d[0], d[3] + 0.002 - i * 0.00003, d[1]));
    });
    disc(COURT_R + 0.18, paving, new THREE.Vector3(0, 0.008, 0));
    put(ground, new THREE.RingGeometry(COURT_R - 0.12, COURT_R + 0.12, 80).rotateX(-Math.PI / 2),
      TYCOON_PARK_COLORS.table, new THREE.Vector3(0, 0.009, 0));
    put(ground, new THREE.RingGeometry(2.42, 2.53, 64).rotateX(-Math.PI / 2),
      TYCOON_PARK_COLORS.table, new THREE.Vector3(0, 0.009, 0));

    const dimensions = { workshop: [7.5, 7], den: [7.5, 7], archive: [7, 6.4], vault: [7, 6.4] };
    Object.keys(ROOMS).forEach(function (key) {
      const frame = RF[key], colour = TYCOON_PARK_COLORS[key], size = dimensions[key];
      if (colour == null) return;
      TYCOON_PARK_STATE.departments.push(key);
      if (frame && size) {
        const pale = new THREE.Color(colour).lerp(new THREE.Color(white), 0.8);
        rectangle(size[0] + 0.45, size[1] + 0.45, colour, frame.at(0, 0.004, 0), frame.yaw);
        rectangle(size[0] - 0.03, size[1] - 0.03, pale, frame.at(0, 0.006, 0), frame.yaw);
        rectangle(3.8, 1.9, white, frame.at(0, 0.008, size[1] / 2 + 0.7), frame.yaw);
        rectangle(3.5, 1.65, colour, frame.at(0, 0.009, size[1] / 2 + 0.7), frame.yaw);
        rectangle(1.45, 1.68, paving, frame.at(0, 0.010, size[1] / 2 + 0.7), frame.yaw);
        badge(frame.at(-2.65, 0, size[1] / 2 + 0.9), frame.yaw, colour, key);
      } else if (key === "observatory" && frame) {
        disc(5.48, paving, frame.at(0, 0.006, 0));
        put(ground, new THREE.RingGeometry(5.23, 5.43, 64).rotateX(-Math.PI / 2), colour, frame.at(0, 0.008, 0));
        badge(frame.at(-2.15, 0, 4.95), frame.yaw, colour, key);
      } else if (key === "dock") {
        rectangle(4.75, 2.22, paving, new THREE.Vector3(23.2, 0.009, -1.5));
        rectangle(4.75, 0.18, colour, new THREE.Vector3(23.2, 0.010, -2.5));
        rectangle(4.75, 0.18, colour, new THREE.Vector3(23.2, 0.010, -0.5));
        badge(new THREE.Vector3(24.95, 0, -2.37), 0, colour, key);
      }
    });

    // Trace the actual walk graph, including detours around desks. Stairs keep their original treads. The
    // table's home nodes can move when its model arrives, so their whole courtyard is paved instead of striped.
    Object.keys(NAV).forEach(function (key) {
      NAV[key].edges.forEach(function (other) {
        if (key >= other || key.startsWith("tb") || other.startsWith("tb")) return;
        const a = NAV[key].p, b = NAV[other].p;
        if (Math.abs(a.y - b.y) > 0.05) return;
        const length = a.distanceTo(b); if (length < 0.05) return;
        const midpoint = a.clone().add(b).multiplyScalar(0.5); midpoint.y += 0.0115;
        rectangle(1.08, length + 0.04, paving, midpoint, Math.atan2(b.x - a.x, b.z - a.z));
        TYCOON_PARK_STATE.routes.push([key, other]);
      });
    });

    const merge = function (list, name, cast) {
      const geometry = mergeGeometries(list, false); if (!geometry) return;
      const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92,
        metalness: 0, depthWrite: !!cast, polygonOffset: !cast, polygonOffsetFactor: 0, polygonOffsetUnits: -1 });
      const mesh = new THREE.Mesh(geometry, material); mesh.name = name;
      // Paint the existing ground after its opaque geometry, without moving the depth buffer toward the camera.
      // A slope-based polygon bias would swallow the crew's thin contact shadows and flat desk rugs.
      if (!cast) mesh.renderOrder = 1;
      mesh.receiveShadow = true; mesh.castShadow = !!cast && Q.shadows;
      mesh.matrixAutoUpdate = false; mesh.updateMatrix(); group.add(mesh);
      list.forEach(function (geo) { geo.dispose(); });
    };
    merge(ground, "tycoon:lawns-and-paving", false); merge(signs, "tycoon:department-pennants", true);
    group.visible = false; scene.add(group); TYCOON_PARK_STATE.group = group;
    return group;
  }
  function tycoonPark(on) {
    if (!TYCOON_PARK_STATE.group && !on) return;
    const group = TYCOON_PARK_STATE.group || tycoonParkBuild(); group.visible = !!on;
  }
  function tycoonParkState() {
    const group = TYCOON_PARK_STATE.group;
    return { on: !!(group && group.visible), meshes: group ? group.children.length : 0,
      departments: TYCOON_PARK_STATE.departments.slice(), paths: TYCOON_PARK_STATE.routes.length };
  }
"""
