#!/usr/bin/env node
// build_cast.mjs: turn the cast's Higgsfield downloads into the page's files (art/CAST_3D.md explains the why).
//
//   node art/cast3d/build_cast.mjs --raw <folder with the downloaded GLBs> [--only clips|<character id>]
//
// Writes into src/nightcrawler/office_assets/:
//   clips.glb          every bought move on ONE reference skeleton (no mesh): idle, talk, sit, cheer, the walks...
//   cast_<id>.glb      each character: mesh + skeleton (bipeds) or mesh only (the rest), webp textures, meshopt
//   cast_manifest.json what the page needs: per clip loop/walk speed, per character kind, height, facing
// A move is re-aimed at load time onto each biped's own skeleton (cast_rig.js), so a new move costs one rigging
// job on any biped and a new office or route costs nothing. Exit codes: 0 done, 1 a source is missing or bad.

import { readFileSync, writeFileSync, existsSync, statSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { NodeIO, Document } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { dedup, prune, resample, textureCompress, meshopt, getBounds, simplify, weld } from '@gltf-transform/functions';
import { MeshoptEncoder, MeshoptDecoder, MeshoptSimplifier } from 'meshoptimizer';
import sharp from 'sharp';
import * as rig from '../../src/nightcrawler/office_assets/cast_rig.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const opt = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
const RAW = resolve(opt('--raw', process.env.CAST_RAW || join(HERE, 'raw')));
const ONLY = opt('--only', null);
const cfg = JSON.parse(readFileSync(join(HERE, 'cast.json'), 'utf8'));
const OUT = resolve(HERE, cfg.out_dir);
const TEX = Number(opt('--tex', 1024));

await MeshoptEncoder.ready; await MeshoptDecoder.ready; await MeshoptSimplifier.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ 'meshopt.encoder': MeshoptEncoder, 'meshopt.decoder': MeshoptDecoder });

const raw = (name) => { const p = join(RAW, name); if (!existsSync(p)) { console.error(`missing source ${p}`); process.exit(1); } return p; };
const BONES = new Set(rig.BIPED_BONES);

// ---------------------------------------------------------------- reading a rigged file
function readRest(doc) {
  const skin = doc.getRoot().listSkins()[0];
  if (!skin) throw new Error('no skin: not a rigged model');
  const joints = skin.listJoints(), names = new Set(joints.map((j) => j.getName()));
  const bones = {};
  for (const j of joints) {
    if (!BONES.has(j.getName())) continue;
    const p = j.getParentNode();
    bones[j.getName()] = { parent: p && names.has(p.getName()) ? p.getName() : null, t: [...j.getTranslation()], r: [...j.getRotation()] };
  }
  for (const b of rig.BIPED_BONES) if (!bones[b]) throw new Error(`bone ${b} missing`);
  const arm = joints.find((j) => j.getName() === 'Hips').getParentNode();
  return { bones, armature: arm ? arm.getScale()[0] : 1 };
}

function readMove(doc) {
  const anim = doc.getRoot().listAnimations()[0];
  if (!anim) throw new Error('no animation');
  let times = null; const rot = {}; let hips = null;
  for (const ch of anim.listChannels()) {
    const n = ch.getTargetNode().getName(), p = ch.getTargetPath(), s = ch.getSampler();
    if (s.getInterpolation() !== 'LINEAR') throw new Error(`${n}.${p}: ${s.getInterpolation()} keys are not supported`);
    const t = Array.from(s.getInput().getArray());
    if (!times) times = t;
    else if (t.length !== times.length || Math.abs(t[t.length - 1] - times[times.length - 1]) > 1e-4) throw new Error(`${n}.${p}: key times differ`);
    if (p === 'rotation' && BONES.has(n)) rot[n] = Array.from(s.getOutput().getArray());
    if (p === 'translation' && n === 'Hips') hips = Array.from(s.getOutput().getArray());
  }
  const t0 = times[0];
  return { source: anim.getName(), times: times.map((x) => x - t0), rot, hips };
}

// ---------------------------------------------------------------- the move library
function libraryDoc(rest, moves) {
  const doc = new Document(); const buf = doc.createBuffer();
  const scene = doc.createScene('clips'); doc.getRoot().setDefaultScene(scene);
  const arm = doc.createNode('Armature').setScale([rest.armature, rest.armature, rest.armature]); scene.addChild(arm);
  const nodes = {};
  for (const n of rig.order(rest)) {
    const b = rest.bones[n];
    nodes[n] = doc.createNode(n).setTranslation(b.t).setRotation(b.r);
    (b.parent ? nodes[b.parent] : arm).addChild(nodes[n]);
  }
  for (const [name, mv] of Object.entries(moves)) {
    const anim = doc.createAnimation(name);
    const input = doc.createAccessor().setType('SCALAR').setArray(new Float32Array(mv.times)).setBuffer(buf);
    const add = (node, path, type, arr) => {
      const out = doc.createAccessor().setType(type).setArray(new Float32Array(arr)).setBuffer(buf);
      const smp = doc.createAnimationSampler().setInput(input).setOutput(out).setInterpolation('LINEAR');
      anim.addSampler(smp).addChannel(doc.createAnimationChannel().setTargetNode(node).setTargetPath(path).setSampler(smp));
    };
    for (const b of rig.order(rest)) if (mv.rot[b]) add(nodes[b], 'rotation', 'VEC4', mv.rot[b]);
    if (mv.hips) add(nodes.Hips, 'translation', 'VEC3', mv.hips);
  }
  return doc;
}

async function buildClips(manifest) {
  const srcs = {};
  for (const [name, c] of Object.entries(cfg.clips)) {
    const doc = await io.read(raw(c.raw));
    srcs[name] = { rest: readRest(doc), move: readMove(doc), spec: c };
  }
  const lib = srcs[cfg.library.rest_from].rest;
  const moves = {};
  manifest.clips = {};
  for (const [name, s] of Object.entries(srcs)) {
    // a walk recorded with travel moves its hips; an in-place walk shows its speed in the planted foot
    const hipsY = s.rest.bones.Hips.t[1], travel = rig.travelSpeed(s.move);
    const own = !s.spec.walk ? 0 : travel / hipsY > 0.05 ? travel : rig.footSpeed(s.rest, s.move);
    const speed = own * (lib.bones.Hips.t[1] / s.rest.bones.Hips.t[1]);
    moves[name] = rig.retarget(s.rest, lib, s.move, {});
    manifest.clips[name] = {
      loop: !!s.spec.loop, walk: !!s.spec.walk, seconds: +s.move.times[s.move.times.length - 1].toFixed(3),
      // ground speed of the move's feet, in the reference skeleton's hip heights per second (the page scales it)
      speed_hips_per_s: +(speed / lib.bones.Hips.t[1]).toFixed(4),
      action: s.spec.action, action_name: s.spec.action_name,
    };
  }
  const doc = libraryDoc(lib, moves);
  await doc.transform(resample({ tolerance: 2e-4 }), meshopt({ encoder: MeshoptEncoder, level: 'medium' }));
  const out = join(OUT, cfg.library.file);
  await io.write(out, doc);
  manifest.library = { file: cfg.library.file, bytes: statSync(out).size, hips_height: lib.bones.Hips.t[1], armature: lib.armature };
  console.log(`clips.glb: ${Object.keys(moves).length} moves, ${(statSync(out).size / 1024).toFixed(0)} KB`);
}

// ---------------------------------------------------------------- the characters
function countTris(root) {
  return root.listMeshes().reduce((n, m) => n + m.listPrimitives().reduce((k, p) => k + (p.getIndices() ? p.getIndices().getCount() : p.getAttribute('POSITION').getCount()) / 3, 0), 0);
}

function skinnedBounds(nodes) {
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  for (const n of nodes) for (const p of n.getMesh().listPrimitives()) {
    const a = p.getAttribute('POSITION'), lo = a.getMinNormalized([]), hi = a.getMaxNormalized([]);
    for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], lo[k]); max[k] = Math.max(max[k], hi[k]); }
  }
  return { min, max };
}

async function buildCharacter(id, spec, manifest) {
  const doc = await io.read(raw(spec.raw));
  const root = doc.getRoot();
  let rest = null;
  if (spec.kind === 'biped') rest = readRest(doc);
  for (const a of root.listAnimations()) a.dispose();  // moves live in clips.glb
  // measured before compression (meshopt quantizes positions and moves their scale into the transforms); a skinned
  // mesh's vertices are already in the skeleton's space, its node transform does not apply
  const skinned = root.listNodes().filter((n) => n.getMesh() && n.getSkin());
  const box = skinned.length ? skinnedBounds(skinned) : getBounds(root.getDefaultScene() || root.listScenes()[0]);
  if (spec.tris && !skinned.length) {  // the static scans come dense (400k-700k triangles): bring them to a phone budget
    const before = countTris(root);
    if (before > spec.tris) await doc.transform(weld(), simplify({ simplifier: MeshoptSimplifier, ratio: spec.tris / before, error: 0.01 }));
  }
  await doc.transform(
    dedup(), prune(),
    textureCompress({ encoder: sharp, targetFormat: 'webp', resize: [spec.tex || TEX, spec.tex || TEX], quality: 82 }),
    meshopt({ encoder: MeshoptEncoder, level: 'medium' }),
  );
  const out = join(OUT, `cast_${id}.glb`);
  await io.write(out, doc);
  const tris = countTris(root);
  manifest.characters[id] = {
    file: `cast_${id}.glb`, kind: spec.kind, role: spec.role || null, bytes: statSync(out).size, tris: Math.round(tris),
    size_m: box.max.map((v, i) => +(v - box.min[i]).toFixed(3)), min_m: box.min.map((v) => +v.toFixed(3)),
    yaw: spec.yaw || 0, walk: spec.walk || null,
    hips_height: rest ? rest.bones.Hips.t[1] : null, armature: rest ? rest.armature : null,
  };
  console.log(`cast_${id}.glb: ${spec.kind}, ${Math.round(tris)} tris, ${(statSync(out).size / 1024).toFixed(0)} KB`);
}

const manifestPath = join(OUT, 'cast_manifest.json');
const manifest = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, 'utf8')) : {};
manifest.version = 1;
manifest.characters = manifest.characters || {};
manifest.note = 'Generated by art/cast3d/build_cast.mjs from art/cast3d/cast.json; do not edit by hand.';
try {
  if (!ONLY || ONLY === 'clips') await buildClips(manifest);
  for (const [id, spec] of Object.entries(cfg.characters)) {
    if (ONLY && ONLY !== id && ONLY !== 'cast') continue;
    if (ONLY === 'clips') continue;
    await buildCharacter(id, spec, manifest);
  }
} catch (e) {
  console.error(`build failed: ${e.message}`); process.exit(1);
}
writeFileSync(manifestPath, JSON.stringify(manifest, null, 1) + '\n');
console.log(`wrote ${manifestPath}`);
