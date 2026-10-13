"""The world's optional steady overview camera; no ledger or trading dependencies."""

TYCOON_CAMERA = r"""
  // A fixed view of the same set. Touch offsets pan the view; only selecting a station moves the camera itself.
  const TYCOON = { on: true, selected: null, room: null, top: 76, bottom: 172, dirty: true,
    ready: false, elapsed: 0.7, width: 0, height: 0, restoreFov: null,
    calm: !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) };
  const TYCOON_FOV = 42, TYCOON_EASE = 0.7;
  const _tycoonOut = new THREE.Vector3(1.45, 1.3, 0.39).normalize();
  const _tycoonRight = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), _tycoonOut).normalize();
  const _tycoonUp = new THREE.Vector3().crossVectors(_tycoonOut, _tycoonRight).normalize();
  const _tycoonAim = { pos: new THREE.Vector3(), look: new THREE.Vector3(), distance: 1 };
  const _tycoonFrom = { pos: new THREE.Vector3(), look: new THREE.Vector3() };
  const _tycoonBase = { pos: new THREE.Vector3(), look: new THREE.Vector3() };
  const _tycoonPose = { pos: new THREE.Vector3(), look: new THREE.Vector3() };
  const _tycoonShift = new THREE.Vector3(), _tycoonRelative = new THREE.Vector3();
  let _tycoonProjection = "";

  function tycoonRoom(key) {
    if (!key || key === "map" || key === "overview") return null;
    if (actors[key]) return actors[key].homeRoom;
    return ROOMS[key] ? key : null;
  }
  function tycoonBounds(top, bottom) {
    const t = Math.max(0, Number(top) || 0), b = Math.max(0, Number(bottom) || 0);
    if (Math.abs(t - TYCOON.top) < 0.5 && Math.abs(b - TYCOON.bottom) < 0.5) return;
    TYCOON.top = t; TYCOON.bottom = b; TYCOON.dirty = true;
  }
  function tycoonSelect(key) {
    const room = tycoonRoom(key);
    if (key && key !== "map" && key !== "overview" && !room) return false;
    if (!TYCOON.on) tycoonEnable(true);
    const next = room ? key : null;
    if (TYCOON.selected === next && !user.yaw && !user.pitch && user.zoom === 1) return true;
    _tycoonFrom.pos.copy(_tycoonPose.pos); _tycoonFrom.look.copy(_tycoonPose.look);
    TYCOON.selected = next; TYCOON.room = room; TYCOON.dirty = true; TYCOON.elapsed = 0;
    user.yaw = 0; user.pitch = 0; user.zoom = 1;
    return true;
  }
  function tycoonEnable(on) {
    const next = !!on;
    if (next) { FLY.on = false; tween = null; }
    if (TYCOON.on === next) { body.classList.toggle("tycoon", next); return; }
    TYCOON.on = next; body.classList.toggle("tycoon", next);
    user.yaw = 0; user.pitch = 0; user.zoom = 1;
    if (next) {
      FLY.on = false; tween = null; TYCOON.ready = false; TYCOON.dirty = true;
    } else {
      camera.clearViewOffset();
      if (TYCOON.restoreFov !== null) camera.fov = TYCOON.restoreFov;
      camera.updateProjectionMatrix(); TYCOON.restoreFov = null; _tycoonProjection = "";
    }
  }
  function tycoonFit() {
    const points = [], rooms = TYCOON.room ? [TYCOON.room] : Object.keys(ROOMS);
    const selectedSpot = TYCOON.room && SPOTS[TYCOON.room];
    if (selectedSpot) {
      const yaw = selectedSpot.homeYaw + 0.55;
      _tycoonOut.set(Math.sin(yaw), 0.75, Math.cos(yaw)).normalize();
    } else _tycoonOut.set(1.45, 1.3, 0.39).normalize();
    _tycoonRight.crossVectors(new THREE.Vector3(0, 1, 0), _tycoonOut).normalize();
    _tycoonUp.crossVectors(_tycoonOut, _tycoonRight).normalize();
    // The town fits room envelopes and doorway labels; a selected station fits its fixed desk and resident.
    // Keep the home anchor even while its worker visits another room, so the viewer controls the camera.
    rooms.forEach(function (key) {
      const spot = SPOTS[key], home = spot && NAV[spot.home], frame = RF[key], lamp = LAMP_AT[key];
      if (TYCOON.room && home) {
        const residentKey = actors[TYCOON.selected] ? TYCOON.selected : Object.keys(actors).find(function (id) { return actors[id].homeRoom === key; });
        const resident = actors[residentKey], visual = residentKey && typeof tycoonCastHeight === "function"
          ? tycoonCastHeight(residentKey) : resident && resident.tycoonVisualHeight;
        const height = typeof visual === "number" && isFinite(visual) && visual > 0 ? visual
          : resident && Number(resident.height) || 1.8;
        const top = Math.max(0.8, height) + 0.45;
        for (const x of [-1.35, 1.35]) for (const y of [0, top]) for (const z of [-1.35, 1.35]) {
          points.push(new THREE.Vector3(home.p.x + x, home.p.y + y, home.p.z + z));
        }
        return;
      }
      // Fit the real toy pavilions, including front awnings and their rear roof
      // edges. Fitting just workers or tiny room boxes clipped outer stations.
      const pavilion = { workshop: [4.4, -4.25, 5.15], den: [4.4, -4.25, 5.15],
        archive: [4.15, -3.95, 4.85], vault: [4.15, -3.95, 4.85] }[key];
      if (frame && pavilion) {
        for (const x of [-pavilion[0], pavilion[0]]) for (const y of [-.05, 4.2]) for (const z of [pavilion[1], pavilion[2]]) {
          points.push(frame.at(x, y, z));
        }
      } else if (key === "observatory" && frame) {
        for (let i = 0; i < 32; i++) for (const y of [-.05, 4.2]) {
          points.push(frame.at(Math.cos(i * Math.PI / 16) * 5.8, y, Math.sin(i * Math.PI / 16) * 5.8));
        }
      } else if (key === "dock") {
        for (const x of [20.05, 26.4]) for (const y of [-.05, 4.2]) for (const z of [-3.65, .65]) {
          points.push(new THREE.Vector3(x, y, z));
        }
      } else {
        const centre = frame ? frame.origin : new THREE.Vector3();
        for (let i = 0; i < 32; i++) for (const y of [-.05, 3.2]) {
          points.push(new THREE.Vector3(centre.x + Math.cos(i * Math.PI / 16) * 6.3, centre.y + y,
            centre.z + Math.sin(i * Math.PI / 16) * 6.3));
        }
      }
      if (home) points.push(home.p.clone().add(new THREE.Vector3(0, 2.8, 0)));
      if (lamp) points.push(lamp.clone().add(new THREE.Vector3(0, 2.2, 0)));
    });
    if (!points.length) points.push(new THREE.Vector3());
    let lx = Infinity, hx = -Infinity, ly = Infinity, hy = -Infinity, lz = Infinity, hz = -Infinity;
    points.forEach(function (p) {
      const x = p.dot(_tycoonRight), y = p.dot(_tycoonUp), z = p.dot(_tycoonOut);
      lx = Math.min(lx, x); hx = Math.max(hx, x); ly = Math.min(ly, y); hy = Math.max(hy, y); lz = Math.min(lz, z); hz = Math.max(hz, z);
    });
    _tycoonAim.look.copy(_tycoonRight).multiplyScalar((lx + hx) / 2)
      .addScaledVector(_tycoonUp, (ly + hy) / 2).addScaledVector(_tycoonOut, (lz + hz) / 2);
    const h = TYCOON.height, w = TYCOON.width, tanY = Math.tan(TYCOON_FOV * Math.PI / 360);
    const marginX = Math.min(64, Math.max(40, w * .05));
    const safeX = Math.max(0.1, (w - marginX) / w), safeY = Math.max(0.1, (h - TYCOON.top - TYCOON.bottom - 40) / h);
    let distance = 9;
    points.forEach(function (p) {
      _tycoonRelative.copy(p).sub(_tycoonAim.look);
      const x = Math.abs(_tycoonRelative.dot(_tycoonRight)), y = Math.abs(_tycoonRelative.dot(_tycoonUp)), z = _tycoonRelative.dot(_tycoonOut);
      distance = Math.max(distance, z + x / (tanY * (w / h) * safeX), z + y / (tanY * safeY));
    });
    _tycoonAim.distance = distance + 0.5;
    if (!TYCOON.room && w < h) {
      // Portrait's width usually limits the fit. Spend some unused space above
      // the town without letting any department enter the measured HUD band.
      const wantedPixels = Math.min(40, Math.max(0, h - TYCOON.top - TYCOON.bottom) * .07);
      let shift = wantedPixels * 2 * tanY * _tycoonAim.distance / h;
      const headroom = (h - TYCOON.top - TYCOON.bottom) / 2 - 20;
      points.forEach(function (p) {
        _tycoonRelative.copy(p).sub(_tycoonAim.look);
        const y = _tycoonRelative.dot(_tycoonUp), depth = _tycoonAim.distance - _tycoonRelative.dot(_tycoonOut);
        shift = Math.min(shift, headroom * 2 * tanY * depth / h - y);
      });
      _tycoonAim.look.addScaledVector(_tycoonUp, -Math.max(0, shift));
    }
    _tycoonAim.pos.copy(_tycoonAim.look).addScaledVector(_tycoonOut, _tycoonAim.distance);
    TYCOON.dirty = false;
  }
  function tycoonPose(dt) {
    const w = Math.max(1, window.innerWidth), h = Math.max(1, window.innerHeight);
    if (w !== TYCOON.width || h !== TYCOON.height) { TYCOON.width = w; TYCOON.height = h; TYCOON.dirty = true; }
    if (TYCOON.dirty) tycoonFit();
    if (!TYCOON.ready || TYCOON.calm) {
      _tycoonBase.pos.copy(_tycoonAim.pos); _tycoonBase.look.copy(_tycoonAim.look); TYCOON.elapsed = TYCOON_EASE; TYCOON.ready = true;
    } else if (TYCOON.elapsed < TYCOON_EASE) {
      TYCOON.elapsed = Math.min(TYCOON_EASE, TYCOON.elapsed + Math.max(0, dt));
      const u = TYCOON.elapsed / TYCOON_EASE, ease = u * u * (3 - 2 * u);
      _tycoonBase.pos.lerpVectors(_tycoonFrom.pos, _tycoonAim.pos, ease); _tycoonBase.look.lerpVectors(_tycoonFrom.look, _tycoonAim.look, ease);
      if (TYCOON.elapsed >= TYCOON_EASE) { _tycoonBase.pos.copy(_tycoonAim.pos); _tycoonBase.look.copy(_tycoonAim.look); }
    } else { _tycoonBase.pos.copy(_tycoonAim.pos); _tycoonBase.look.copy(_tycoonAim.look); }
    const zoom = Math.max(0.5, Math.min(1.8, Number(user.zoom) || 1));
    const height = 2 * _tycoonBase.pos.distanceTo(_tycoonBase.look) * Math.tan(TYCOON_FOV * Math.PI / 360);
    _tycoonShift.copy(_tycoonRight).multiplyScalar((user.yaw || 0) * height * (w / h) * 0.7)
      .addScaledVector(_tycoonUp, -(user.pitch || 0) * height * 0.8);
    _tycoonPose.look.copy(_tycoonBase.look).add(_tycoonShift);
    _tycoonPose.pos.copy(_tycoonBase.pos).sub(_tycoonBase.look).multiplyScalar(zoom).add(_tycoonPose.look);
    return _tycoonPose;
  }
  function tycoonCameraUpdate(dt, t) {
    if (!TYCOON.on) return false;
    if (TYCOON.restoreFov === null || camera.fov !== TYCOON_FOV) TYCOON.restoreFov = camera.fov;
    const pose = tycoonPose(dt), w = TYCOON.width, h = TYCOON.height;
    const projection = [w, h, TYCOON.top, TYCOON.bottom].join("|");
    if (projection !== _tycoonProjection || camera.fov !== TYCOON_FOV || !(camera.view && camera.view.enabled)) {
      camera.fov = TYCOON_FOV;
      // Shift the optical centre into the free band, retaining full-screen projection for toScreen() and taps.
      camera.setViewOffset(w, h, 0, (TYCOON.bottom - TYCOON.top) / 2, w, h);
      _tycoonProjection = projection;
    }
    FLY.on = false; tween = null; shotKey = "tycoon";
    cam.pos.copy(pose.pos); cam.look.copy(pose.look);
    camera.position.copy(pose.pos); camera.lookAt(pose.look); camera.updateMatrixWorld(true);
    sky.position.copy(camera.position); cloudU.uCam.value.copy(camera.position);
    if (Q.shadows) { sun.target.position.copy(cam.look); sun.position.copy(cam.look).addScaledVector(sun.userData.dir || sunDir, 60); }
    void t;
    return true;
  }
  function tycoonCameraState() {
    return { on: TYCOON.on, selected: TYCOON.selected, room: TYCOON.room,
      position: _tycoonPose.pos.toArray(), look: _tycoonPose.look.toArray(), zoom: user.zoom,
      settled: TYCOON.elapsed >= TYCOON_EASE, top: TYCOON.top, bottom: TYCOON.bottom };
  }
"""
