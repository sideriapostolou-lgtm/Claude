// cast_rig.js: retarget skeletal animation between the cast's rigs (plain math, no imports).
//
// Every biped in the cast (Voss, Pip, Rook, Jet) was rigged once by the same auto-rigger, so the four skeletons
// share bone NAMES (Hips, Spine, Spine01, Spine02, neck, Head, Left/Right Shoulder, Arm, ForeArm, Hand, UpLeg, Leg,
// Foot, ToeBase) but not their rest poses: each bone sits where that character's body puts it. A move bought once
// (an "idle", a "talk", a "cheer") is stored on ONE reference skeleton (clips.glb) and re-aimed here onto any of
// them, so a new move or a new office never needs a new paid generation.
//
// The method: for every bone and frame, the move's WORLD rotation away from the reference rest pose is applied to
// the target bone's own world rest rotation (world delta), then turned back into a local rotation under the target
// parent's animated world rotation. The hips' travel is scaled by the ratio of hip heights. Linear travel over the
// clip on the ground plane can be removed (the page moves the character itself).
//
// The same file runs in the browser (cast_motion.js) and in Node (art/cast3d/build_cast.mjs), so the build step
// and the page cannot drift apart.

export const BIPED_BONES = [
  "Hips", "Spine", "Spine01", "Spine02", "neck", "Head",
  "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
  "RightShoulder", "RightArm", "RightForeArm", "RightHand",
  "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase",
  "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase",
];

// ---------------------------------------------------------------- quaternions as [x, y, z, w]
export function qmul(a, b) {
  return [
    a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
    a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
    a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
  ];
}
export function qinv(a) {
  const n = a[0] * a[0] + a[1] * a[1] + a[2] * a[2] + a[3] * a[3] || 1;
  return [-a[0] / n, -a[1] / n, -a[2] / n, a[3] / n];
}
export function qnorm(a) {
  const n = Math.hypot(a[0], a[1], a[2], a[3]) || 1;
  return [a[0] / n, a[1] / n, a[2] / n, a[3] / n];
}
export function qdot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]; }
export function qslerp(a, b, t) {
  let d = qdot(a, b), bb = b;
  if (d < 0) { d = -d; bb = [-b[0], -b[1], -b[2], -b[3]]; }
  if (d > 0.9995) return qnorm([a[0] + (bb[0] - a[0]) * t, a[1] + (bb[1] - a[1]) * t, a[2] + (bb[2] - a[2]) * t, a[3] + (bb[3] - a[3]) * t]);
  const th = Math.acos(d), s = Math.sin(th), wa = Math.sin((1 - t) * th) / s, wb = Math.sin(t * th) / s;
  return [a[0] * wa + bb[0] * wb, a[1] * wa + bb[1] * wb, a[2] * wa + bb[2] * wb, a[3] * wa + bb[3] * wb];
}
export function qaxis(ax, ay, az, angle) {
  const n = Math.hypot(ax, ay, az) || 1, s = Math.sin(angle / 2);
  return [ax / n * s, ay / n * s, az / n * s, Math.cos(angle / 2)];
}

// ---------------------------------------------------------------- rest poses
// A rest pose: { bones: { name: { parent: name|null, t: [x,y,z], r: [x,y,z,w] } } }. Bones whose parent is not in
// the map hang off an identity root (the rig's Armature node only scales; it never rotates).
export function order(rest) {
  const out = [], seen = new Set();
  const visit = (n) => {
    if (seen.has(n) || !rest.bones[n]) return;
    const p = rest.bones[n].parent;
    if (p && rest.bones[p]) visit(p);
    seen.add(n); out.push(n);
  };
  Object.keys(rest.bones).forEach(visit);
  return out;
}
export function worldRest(rest) {
  const w = {};
  for (const n of order(rest)) {
    const b = rest.bones[n], p = b.parent && w[b.parent];
    w[n] = p ? qmul(p, b.r) : b.r.slice();
  }
  return w;
}

// ---------------------------------------------------------------- frames
// A move: { times: number[], rot: { bone: number[4n] }, hips: number[3n] | null }. Every rotation is LOCAL, keyed
// at the shared times. retarget() returns a move of the same shape for the target rest pose.
export function retarget(src, dst, move, opts = {}) {
  const n = move.times.length, ws0 = worldRest(src), wd0 = worldRest(dst), names = order(dst);
  const out = { times: Array.from(move.times), rot: {}, hips: null };
  const corr = {};  // per bone: inverse(source world rest) * target world rest
  for (const b of names) if (ws0[b]) corr[b] = qmul(qinv(ws0[b]), wd0[b]);
  for (const b of names) out.rot[b] = new Array(4 * n);
  const ws = {}, wd = {};
  for (let f = 0; f < n; f++) {
    for (const b of names) {
      const sb = src.bones[b], db = dst.bones[b];
      const local = move.rot[b] ? move.rot[b].slice(4 * f, 4 * f + 4) : (sb ? sb.r : db.r);
      const sp = sb && sb.parent && ws[sb.parent] ? ws[sb.parent] : null;
      ws[b] = sp ? qmul(sp, local) : local;
      // the target bone's world rotation: the move's world rotation carried onto the target rest
      const want = corr[b] ? qmul(ws[b], corr[b]) : (db.parent && wd[db.parent] ? qmul(wd[db.parent], db.r) : db.r);
      const dp = db.parent && wd[db.parent] ? wd[db.parent] : null;
      let q = qnorm(dp ? qmul(qinv(dp), want) : want);
      wd[b] = want;
      if (f > 0) {  // keep each track on one side of the double cover so interpolation never takes the long way
        const prev = out.rot[b].slice(4 * f - 4, 4 * f);
        if (qdot(prev, q) < 0) q = [-q[0], -q[1], -q[2], -q[3]];
      }
      out.rot[b].splice(4 * f, 4, q[0], q[1], q[2], q[3]);
    }
  }
  if (move.hips && src.bones.Hips && dst.bones.Hips) {
    const s0 = src.bones.Hips.t, d0 = dst.bones.Hips.t;
    const ratio = opts.hipsRatio ?? (Math.abs(s0[1]) > 1e-6 ? d0[1] / s0[1] : 1);
    const h = move.hips, last = 3 * (n - 1);
    const drift = opts.keepTravel ? [0, 0, 0] : [h[last] - h[0], 0, h[last + 2] - h[2]];
    out.hips = new Array(3 * n);
    for (let f = 0; f < n; f++) {
      const u = n > 1 ? f / (n - 1) : 0;
      for (let k = 0; k < 3; k++) {
        const v = h[3 * f + k] - drift[k] * u;
        out.hips[3 * f + k] = d0[k] + (v - s0[k]) * ratio;
      }
    }
  }
  return out;
}

// The move's average ground speed (rest units per second) before its travel is removed: the page matches the
// character's walking speed to its feet with it.
export function travelSpeed(move) {
  const n = move.times.length;
  if (!move.hips || n < 2) return 0;
  const h = move.hips, last = 3 * (n - 1), dt = move.times[n - 1] - move.times[0];
  return dt > 0 ? Math.hypot(h[last] - h[0], h[last + 2] - h[2]) / dt : 0;
}

// ---------------------------------------------------------------- feet
export function qrot(q, v) {  // rotate vector v by unit quaternion q
  const [x, y, z, w] = q, [vx, vy, vz] = v;
  const ix = w * vx + y * vz - z * vy, iy = w * vy + z * vx - x * vz, iz = w * vz + x * vy - y * vx, iw = -x * vx - y * vy - z * vz;
  return [ix * w + iw * -x + iy * -z - iz * -y, iy * w + iw * -y + iz * -x - ix * -z, iz * w + iw * -z + ix * -y - iy * -x];
}

// World positions (rest units, the rig's armature space) of the named bones at frame f of a move.
export function pose(rest, move, f, names) {
  const wr = {}, wp = {};
  for (const b of order(rest)) {
    const rb = rest.bones[b];
    const r = move.rot[b] ? move.rot[b].slice(4 * f, 4 * f + 4) : rb.r;
    const t = b === "Hips" && move.hips ? move.hips.slice(3 * f, 3 * f + 3) : rb.t;
    if (rb.parent && wr[rb.parent]) {
      const o = qrot(wr[rb.parent], t);
      wp[b] = [wp[rb.parent][0] + o[0], wp[rb.parent][1] + o[1], wp[rb.parent][2] + o[2]];
      wr[b] = qmul(wr[rb.parent], r);
    } else { wp[b] = t.slice(); wr[b] = r; }
  }
  const out = {};
  for (const n of names) out[n] = wp[n];
  return out;
}

// The ground speed an in-place walk implies (rest units per second): while a foot is planted (the lower of the
// two toes), it slides backward under the body at the walking speed. Median over the planted frames; 0 for a move
// whose feet do not cycle. The facing is +Z, as the rigger exports the cast.
export function footSpeed(rest, move) {
  const n = move.times.length;
  if (n < 3) return 0;
  const toes = ["LeftToeBase", "RightToeBase"], P = [];
  for (let f = 0; f < n; f++) P.push(pose(rest, move, f, toes));
  const v = [];
  for (let f = 1; f < n - 1; f++) {
    const planted = P[f].LeftToeBase[1] < P[f].RightToeBase[1] ? "LeftToeBase" : "RightToeBase";
    const dt = move.times[f + 1] - move.times[f - 1];
    if (dt <= 0) continue;
    const vz = (P[f + 1][planted][2] - P[f - 1][planted][2]) / dt, vx = (P[f + 1][planted][0] - P[f - 1][planted][0]) / dt;
    if (vz < 0) v.push(Math.hypot(vx, vz));
  }
  if (v.length < n / 4) return 0;
  v.sort((a, b) => a - b);
  return v[Math.floor(v.length / 2)];
}
