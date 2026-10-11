// cast_motion.js: the cast's bodies in motion on the page (three.js; loaded by the world page).
//
// * One move library (clips.glb, cast_manifest.json) drives every biped: each move is re-aimed at load time onto
//   the character's own skeleton (cast_rig.js), so Voss, Pip, Rook and Jet share every move bought once.
// * On top of the moves, layers written in code cost nothing to extend: the head turns toward whoever is talking,
//   the arms reach (two-bone IK) for a keyboard, a screen or a parcel, Nyx's tentacles ripple, Mote bobs in the
//   bell, Jet's eyes blink. A new office is new target points, not new animation.
// * Walking matches the feet: the playback rate follows the actual ground speed (no sliding).
// Nothing here writes words or numbers on screen; the page decides what each character does from the ledger.

import * as THREE from "three";
import { BIPED_BONES, retarget } from "./cast_rig.js";

const FPS = 30;
const _v1 = new THREE.Vector3(), _v2 = new THREE.Vector3(), _v3 = new THREE.Vector3(), _q1 = new THREE.Quaternion(),
  _q2 = new THREE.Quaternion(), _q3 = new THREE.Quaternion(), _qa = new THREE.Quaternion(), _qb = new THREE.Quaternion();
// scratch for the per-frame layers (look, reach): nothing is allocated while the page runs
const _UP = new THREE.Vector3(0, 1, 0), _s = new THREE.Vector3(), _to = new THREE.Vector3(), _local = new THREE.Vector3(),
  _side = new THREE.Vector3(), _pole = new THREE.Vector3(), _axis = new THREE.Vector3(), _elbow = new THREE.Vector3(),
  _hand = new THREE.Vector3(), _tp = new THREE.Vector3(), _rq = new THREE.Quaternion();

// ---------------------------------------------------------------- reading rigs and moves
function boneMap(root) {
  const out = {};
  root.traverse((o) => {
    if (!(o.isBone || o.type === "Object3D" || o.isObject3D)) return;
    const base = o.name.replace(/_\d+$/, "");
    if (BIPED_BONES.includes(o.name) && !out[o.name]) out[o.name] = o;
    else if (BIPED_BONES.includes(base) && !out[base]) out[base] = o;
  });
  return out;
}

function restOf(bones) {
  const rest = { bones: {} };
  for (const n of BIPED_BONES) {
    const b = bones[n];
    if (!b) return null;
    const p = b.parent && BIPED_BONES.includes(b.parent.name.replace(/_\d+$/, "")) ? b.parent.name.replace(/_\d+$/, "") : null;
    rest.bones[n] = { parent: p, t: b.position.toArray(), r: b.quaternion.toArray() };
  }
  return rest;
}

// three's clip -> a move keyed at FPS (the build may store each track at its own key times).
function clipToMove(clip) {
  const n = Math.max(2, Math.round(clip.duration * FPS) + 1), times = [];
  for (let i = 0; i < n; i++) times.push((clip.duration * i) / (n - 1));
  const move = { times, rot: {}, hips: null };
  for (const tr of clip.tracks) {
    const dot = tr.name.lastIndexOf("."), node = tr.name.slice(0, dot).replace(/_\d+$/, ""), prop = tr.name.slice(dot + 1);
    if (!BIPED_BONES.includes(node)) continue;
    const it = tr.createInterpolant(), size = tr.getValueSize(), out = new Array(size * n);
    for (let i = 0; i < n; i++) { const v = it.evaluate(times[i]); for (let k = 0; k < size; k++) out[i * size + k] = v[k]; }
    if (prop === "quaternion") move.rot[node] = out;
    else if (prop === "position" && node === "Hips") move.hips = out;
  }
  return move;
}

function moveToClip(name, move, bones) {
  const tracks = [];
  for (const [b, vals] of Object.entries(move.rot)) {
    if (bones[b]) tracks.push(new THREE.QuaternionKeyframeTrack(bones[b].name + ".quaternion", move.times, vals));
  }
  if (move.hips && bones.Hips) tracks.push(new THREE.VectorKeyframeTrack(bones.Hips.name + ".position", move.times, move.hips));
  return new THREE.AnimationClip(name, move.times[move.times.length - 1], tracks);
}

// ---------------------------------------------------------------- the library
export class MoveLibrary {
  constructor(gltf, manifest) {
    this.manifest = manifest || { clips: {} };
    const bones = boneMap(gltf.scene);
    this.rest = restOf(bones);
    this.moves = {};
    for (const clip of gltf.animations) this.moves[clip.name] = clipToMove(clip);
    this.cache = new Map();
  }
  has(name) { return !!this.moves[name]; }
  info(name) { return (this.manifest.clips || {})[name] || {}; }
  // The move re-aimed onto one rig (cached per rig and move).
  clipFor(rigKey, rest, bones, name) {
    const key = rigKey + "|" + name;
    if (this.cache.has(key)) return this.cache.get(key);
    const move = this.moves[name];
    if (!move || !rest || !this.rest) return null;
    const clip = moveToClip(name, retarget(this.rest, rest, move, {}), bones);
    this.cache.set(key, clip);
    return clip;
  }
}

// ---------------------------------------------------------------- an actor
// spec: { id, kind: "biped"|"octopus"|"blob"|"prop", walk: move name, height: metres, yaw: radians }
export class Actor {
  constructor(model, spec, library) {
    this.spec = spec; this.library = library; this.id = spec.id;
    this.root = new THREE.Group(); this.root.name = "actor:" + spec.id;
    this.model = model; this.root.add(model);
    this.time = Math.random() * 10;
    this.state = "idle"; this.heading = 0; this.turnRate = 5;
    this.path = []; this.speed = 0; this.onArrive = null;
    this.look = null; this.lookW = 0;
    this.reach = { left: null, right: null, w: 0, typing: false };
    this.mixer = null; this.actions = {}; this.current = null; this.oneShot = null;
    this.materials = [];
    model.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; [].concat(o.material).forEach((m) => this.materials.push(m)); } });
    this._fit();
    if (spec.kind === "biped") this._rig();
    if (spec.kind === "octopus") this._tentacles();
    this.blinkAt = this.time + 2 + Math.random() * 3;
  }

  // scale the model to its height and stand it on the floor, facing +Z (the world's "forward" for the actor)
  _fit() {
    this.model.updateMatrixWorld(true);
    this.model.traverse((o) => { if (o.isSkinnedMesh) { o.skeleton.update(); o.computeBoundingBox(); } });
    const box = new THREE.Box3().setFromObject(this.model), size = box.getSize(_v1);
    const s = (this.spec.height || 1) / Math.max(1e-6, size.y);
    this.model.scale.multiplyScalar(s);
    this.model.rotation.y = this.spec.yaw || 0;
    this.model.updateMatrixWorld(true);
    const b2 = new THREE.Box3().setFromObject(this.model), c = b2.getCenter(_v2);
    this.model.position.x -= c.x; this.model.position.z -= c.z; this.model.position.y -= b2.min.y;
    this.size = b2.getSize(new THREE.Vector3());
  }

  _rig() {
    this.bones = boneMap(this.model);
    this.rest = restOf(this.bones);
    if (!this.rest) { this.spec.kind = "prop"; return; }
    this.mixer = new THREE.AnimationMixer(this.model);
    // world size of one rest unit, and the hips' height: the walk's speed is in hip heights per second
    this.bones.Hips.parent.updateWorldMatrix(true, false);
    this.unit = this.bones.Hips.parent.getWorldScale(_v1).x / Math.max(1e-6, this.root.getWorldScale(_v2).x);
    this.hipsHeight = this.rest.bones.Hips.t[1] * this.unit;
    this.restQ = {};
    for (const n of BIPED_BONES) this.restQ[n] = this.bones[n].quaternion.clone();
    this.armLen = {};
    for (const side of ["Left", "Right"]) {
      const a = this.bones[side + "Arm"], f = this.bones[side + "ForeArm"], h = this.bones[side + "Hand"];
      this.armLen[side] = [f.position.length(), h.position.length()];
      void a;
    }
  }

  action(name) {
    if (!this.mixer) return null;
    if (this.actions[name]) return this.actions[name];
    const clip = this.library.clipFor(this.id, this.rest, this.bones, name);
    if (!clip) return null;
    const a = this.mixer.clipAction(clip);
    const info = this.library.info(name);
    if (!info.loop) { a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; }
    this.actions[name] = a;
    return a;
  }

  // Loop a move (cross-faded); a one-shot move (cheer, shrug, nod) plays once, then the loop comes back.
  play(name, fade = 0.35) {
    const a = this.action(name);
    if (!a) return false;
    const info = this.library.info(name);
    if (!info.loop) {
      if (this.oneShot) this.oneShot.fadeOut(fade);
      a.reset().setEffectiveWeight(1).fadeIn(fade).play();
      this.oneShot = a; this.oneShotEnds = this.time + (a.getClip().duration - fade);
      if (this.current) this.current.fadeOut(fade);
      return true;
    }
    if (this.current === a) return true;
    a.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).fadeIn(fade).play();
    if (this.current) this.current.fadeOut(fade);
    this.current = a; this.loopName = name;
    return true;
  }

  // Walk along points [{x, z}], at the walk's own speed; then call back.
  walkTo(points, onArrive) {
    this.path = points.map((p) => new THREE.Vector3(p.x, 0, p.z));
    this.onArrive = onArrive || null;
    if (this.spec.kind === "biped") this.play(this.spec.walk || "walk_casual", 0.25);
  }
  stop() { this.path = []; }
  walkSpeed() {
    const info = this.library.info(this.spec.walk || "walk_casual");
    const k = info.speed_hips_per_s || 0;
    return this.spec.kind === "biped" && k > 0 ? k * this.hipsHeight * this.root.scale.x : (this.spec.speed || 0.9);
  }

  // Turn the head toward a world point (null: look ahead again). Copies the point (no allocation after the first).
  lookAt(worldPos, weight = 1) {
    if (worldPos) { this.look = (this.look || new THREE.Vector3()).copy(worldPos); this.lookTargetW = weight; }
    else this.lookTargetW = 0;
  }
  // Hands to world points (null: let go). typing=true taps the fingers. The hands keep their last points while
  // they let go, so the arms ease back instead of snapping.
  reachTo(left, right, typing = false) {
    const r = this.reach;
    if (left) r.left = (r.left || new THREE.Vector3()).copy(left);
    if (right) r.right = (r.right || new THREE.Vector3()).copy(right);
    if (left && !right) r.right = null;
    if (right && !left) r.left = null;
    r.typing = typing; r.target = left || right ? 1 : 0;
  }

  update(dt) {
    this.time += dt;
    this._move(dt);
    if (this.mixer) {
      if (this.oneShot && this.time >= this.oneShotEnds) {
        this.oneShot.fadeOut(0.35); this.oneShot = null;
        if (this.current) this.current.reset().fadeIn(0.35).play();
      }
      this.mixer.update(dt);
      this._layers(dt);
    }
    if (this.spec.kind === "octopus" || this.spec.kind === "blob") this._float(dt);
    this._blink(dt);
  }

  _move(dt) {
    if (!this.path.length) return;
    const p = this.root.position, goal = this.path[0];
    _v1.set(goal.x - p.x, 0, goal.z - p.z);
    const d = _v1.length(), v = this.walkSpeed();
    if (d < Math.max(0.05, v * dt * 1.5)) {
      p.x = goal.x; p.z = goal.z; this.path.shift();
      if (!this.path.length) {
        if (this.spec.kind === "biped") this.play("idle", 0.3);
        const cb = this.onArrive; this.onArrive = null; if (cb) cb(this);
      }
      return;
    }
    const want = Math.atan2(_v1.x, _v1.z);
    let diff = want - this.heading; diff = Math.atan2(Math.sin(diff), Math.cos(diff));
    this.heading += Math.sign(diff) * Math.min(Math.abs(diff), this.turnRate * dt);
    this.root.rotation.y = this.heading;
    const facing = Math.max(0, Math.cos(diff));  // slow down while turning hard
    const step = v * dt * (0.35 + 0.65 * facing);
    p.x += Math.sin(this.heading) * step; p.z += Math.cos(this.heading) * step;
    if (this.current && this.spec.kind === "biped") this.current.setEffectiveTimeScale(0.35 + 0.65 * facing);
  }

  // ---------------------------------------------------------- code-written layers
  _rotateWorld(bone, q) {  // apply world rotation q to a bone (keeps its children's local poses)
    bone.parent.getWorldQuaternion(_qa);
    _qb.copy(_qa).invert().multiply(q).multiply(_qa);
    bone.quaternion.premultiply(_qb);
    bone.updateMatrixWorld(true);
  }
  _aim(bone, toWorld, weight) {  // turn a bone so its length axis (+Y) points at a world point
    bone.updateMatrixWorld(true);
    const from = bone.getWorldPosition(_v1);
    const cur = _v2.set(0, 1, 0).applyQuaternion(bone.getWorldQuaternion(_q1)).normalize();
    const want = _v3.copy(toWorld).sub(from).normalize();
    _q1.setFromUnitVectors(cur, want);
    if (weight < 1) _q1.slerp(_q2.identity(), 1 - weight);
    this._rotateWorld(bone, _q1);
  }
  _ik(side, target, w) {  // two-bone IK: upper arm and forearm reach a world point, elbow bent outward and down
    const arm = this.bones[side + "Arm"], fore = this.bones[side + "ForeArm"];
    arm.updateMatrixWorld(true);
    const s = arm.getWorldPosition(_s);
    const scale = arm.getWorldScale(_v1).x;
    const a = this.armLen[side][0] * scale, b = this.armLen[side][1] * scale;
    const to = _to.copy(target).sub(s); let d = to.length();
    d = Math.max(1e-4, Math.min(d, (a + b) * 0.999)); to.setLength(d);
    const cosA = THREE.MathUtils.clamp((a * a + d * d - b * b) / (2 * a * d), -1, 1), ang = Math.acos(cosA);
    // the actor's own right (its world turn: the root may sit under a parent that walks and turns it)
    const right = _side.set(side === "Left" ? 1 : -1, 0, 0).applyQuaternion(this.root.getWorldQuaternion(_rq));
    const pole = _pole.copy(right).sub(_UP).normalize();
    const axis = _axis.crossVectors(to, pole).normalize();
    const elbow = _elbow.copy(to).normalize().applyAxisAngle(axis, ang).multiplyScalar(a).add(s);  // turned toward the pole
    this._aim(arm, elbow, w);
    this._aim(fore, _hand.copy(s).add(to), w);
  }
  _layers(dt) {
    // head turn toward the look target (neck 35 %, head 65 %), limited to what a neck can do
    this.lookW += ((this.lookTargetW || 0) - this.lookW) * Math.min(1, dt * 3);
    if (this.look && this.lookW > 0.01) {
      const head = this.bones.Head;
      head.updateMatrixWorld(true);
      const hp = head.getWorldPosition(_v1), to = _v2.copy(this.look).sub(hp);
      const rootQ = this.root.getWorldQuaternion(_rq);
      const local = _local.copy(to).applyQuaternion(_q1.copy(rootQ).invert());
      const yaw = THREE.MathUtils.clamp(Math.atan2(local.x, local.z), -1.0, 1.0);
      const pitch = THREE.MathUtils.clamp(Math.atan2(local.y, Math.hypot(local.x, local.z)), -0.45, 0.35);
      const side = _side.set(1, 0, 0).applyQuaternion(rootQ);
      for (let i = 0; i < 2; i++) {
        const k = i ? 0.65 : 0.35;
        _q1.setFromAxisAngle(_UP, yaw * k * this.lookW); _q2.setFromAxisAngle(side, -pitch * k * this.lookW);
        this._rotateWorld(this.bones[i ? "Head" : "neck"], _q3.copy(_q1).multiply(_q2));
      }
    }
    // hands reach (typing taps the fingers)
    const r = this.reach;
    r.w = (r.w || 0) + ((r.target || 0) - (r.w || 0)) * Math.min(1, dt * 4);
    if (r.w > 0.01) {
      const t = this.time;
      for (let i = 0; i < 2; i++) {
        const p = i ? r.right : r.left, ph = i ? 1.7 : 0;
        if (!p) continue;
        const tp = _tp.copy(p);
        if (r.typing) tp.y += Math.max(0, Math.sin(t * 11 + ph) * Math.sin(t * 3.1 + ph)) * 0.025 * this.root.scale.y;
        this._ik(i ? "Right" : "Left", tp, r.w);
      }
    }
  }

  _float() {  // Nyx and Mote: a slow breath and bob (their meshes have no skeleton)
    const t = this.time, m = this.model;
    if (!this.base) this.base = { y: m.position.y, s: m.scale.clone() };
    const b = Math.sin(t * 1.6);
    m.position.y = this.base.y + (this.spec.kind === "blob" ? 0.03 + 0.03 * b : 0.01 * b) * (this.spec.height || 1);
    m.scale.set(this.base.s.x * (1 + 0.025 * b), this.base.s.y * (1 - 0.02 * b), this.base.s.z * (1 + 0.025 * b));
    if (this.tentacleU) this.tentacleU.value = t;
  }

  _tentacles() {  // Nyx: tentacles ripple below the head (a vertex wave; the shader keeps the rest of the material)
    const box = new THREE.Box3().setFromObject(this.model);
    const inv = new THREE.Matrix4();
    const u = { value: 0 }; this.tentacleU = u;
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      o.geometry.computeBoundingBox();
      const gb = o.geometry.boundingBox, h = gb.max.y - gb.min.y, cut = gb.min.y + h * 0.42;
      [].concat(o.material).forEach((mat) => {
        mat.onBeforeCompile = (sh) => {
          sh.uniforms.uT = u;
          sh.vertexShader = "uniform float uT;\n" + sh.vertexShader.replace("#include <begin_vertex>",
            "#include <begin_vertex>\n" +
            `float tm = clamp((${cut.toFixed(5)} - position.y) / ${(h * 0.42).toFixed(5)}, 0.0, 1.0);\n` +
            "float ang = atan(position.z, position.x);\n" +
            `float wv = sin(uT * 2.2 + ang * 4.0 + position.y * ${(12 / h).toFixed(4)}) * tm * tm * ${(h * 0.035).toFixed(5)};\n` +
            "transformed.x += cos(ang) * wv; transformed.z += sin(ang) * wv;\n" +
            `transformed.y += sin(uT * 1.7 + ang * 3.0) * tm * ${(h * 0.012).toFixed(5)};`);
        };
        mat.needsUpdate = true;
      });
    });
    void box; void inv;
  }

  _blink() {  // eyes that glow (Jet's visor) blink now and then
    if (this.time < this.blinkAt) return;
    if (!this.glow) this.glow = this.materials.filter((m) => m.emissiveMap || (m.emissive && m.emissive.getHex()));
    const glow = this.glow;
    if (!glow.length) { this.blinkAt = Infinity; return; }
    const phase = this.time - this.blinkAt;
    const k = phase < 0.07 ? 1 - phase / 0.07 : phase < 0.16 ? (phase - 0.07) / 0.09 : 1;
    glow.forEach((m) => { if (m._baseEI === undefined) m._baseEI = m.emissiveIntensity; m.emissiveIntensity = m._baseEI * Math.max(0.05, k); });
    if (phase >= 0.16) this.blinkAt = this.time + 2.5 + Math.random() * 4;
  }
}

// ---------------------------------------------------------------- loading
// loader: a GLTFLoader (with the meshopt decoder set); base: the URL prefix of the asset files.
export async function loadLibrary(loader, base) {
  const [gltf, manifest] = await Promise.all([
    loader.loadAsync(base + "clips.glb"),
    fetch(base + "cast_manifest.json", { credentials: "same-origin" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  return new MoveLibrary(gltf, manifest);
}

export async function loadActor(loader, base, spec, library) {
  const gltf = await loader.loadAsync(base + spec.file);
  return new Actor(gltf.scene, spec, library);
}
