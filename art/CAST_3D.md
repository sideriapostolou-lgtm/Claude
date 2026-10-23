# The cast in 3D (Higgsfield)

Sideri chose Higgsfield for the cast on 2026-10-09 ("take advantage, be very thorough, make it so they move, and in
the future it doesn't cost more credits if we want him working in a different office or moving differently").
This file records what was generated, what it cost, how it becomes the page's files, and how to add moves, offices
and characters later **without spending credits**.

## What exists

| Who | Model | How it moves |
|---|---|---|
| Voss (cobalt owl) | Meshy multi-image (3 views) + Meshy rig | every move in the library; own walk: penguin waddle |
| Pip (orange fox) | Meshy multi-image (3 views) + Meshy rig | every move; own walk: skip |
| Rook (slate golem, 1.8 m) | Meshy multi-image (3 views) + Meshy rig | every move; own walk: heavy orc walk; amber eyes drawn in code |
| Jet (courier robot) | Meshy multi-image (3 views) + Meshy rig | every move; own walk: quick walk; visor eyes blink in code |
| Nyx (octopus) | Tripo multiview (3 views), 45k triangles | tentacle ripple and breath written in code |
| Mote (mint creature) | Tripo multiview (3 views), 30k triangles | bob and squash in code; the glass bell is drawn in code |
| Mote's brass cart | Tripo multiview (2 views) | rolls in code |

Files (in `src/nightcrawler/office_assets/`): `cast_<id>.glb` (mesh + skeleton, webp textures, meshopt),
`clips.glb` (the move library, no mesh), `cast_manifest.json` (per move: loop, seconds, ground speed; per
character: kind, size, hip height, facing), `cast_rig.js` (the retarget math, shared with the build) and
`cast_motion.js` (the bodies in motion on the page).

## The move library (bought once, used by every biped)

| Name | Library action (id) | Plays | Length |
|---|---|---|---|
| idle | Idle (0) | loop | 4 s |
| chat | Stand_and_Chat (56) | loop | 5.2 s |
| talk | Talk_with_Hands_Open (313) | loop | 4 s |
| listen | Listening_Gesture (47) | loop | 9.3 s |
| nod | Agree_Gesture (25) | once | 13 s |
| sit | Chair_Sit_Idle_M (33) | loop | 10.7 s |
| sit_talk | Sitting_Answering_Questions (307) | loop | 9.7 s |
| cheer | Victory_Cheer (59) | once | 9.3 s |
| worried | Headache_Relief (316) | once | 4.8 s |
| shrug | Shrug (317) | once | 2 s |
| think | Confused_Scratch (36) | once | 11.5 s |
| scheme | Scheming_Hand_Rub (318) | once | 3.3 s |
| wave | Wave_One_Hand (290) | once | 4.1 s |
| drink | Stand_and_Drink (342) | loop | 8.9 s |
| look | Long_Breathe_and_Look_Around (336) | loop | 11.3 s |
| carry | Carry_Heavy_Object_Walk_inplace (611) | loop | 6.5 s |
| walk_casual | Casual_Walk_inplace (613) | loop | 4.2 s |
| walk_skip | Skip_Forward_inplace (668) | loop | 2.8 s |
| walk_quick | Quick_Walk (115) | loop | 3 s |
| walk_penguin | penguin_walk (62) | loop | 2 s |
| walk_heavy | Slow_Orc_Walk_inplace (669) | loop | 5.5 s |

Why every biped can use every move: all four bipeds were rigged by the same auto-rigger, so their skeletons share
bone names. Each move is stored once on a reference skeleton (Pip's idle rig) and re-aimed at load time onto each
character's own skeleton (`cast_rig.js`: the move's world rotation away from the reference rest pose is applied to
the character's own rest pose; the hips' bob scales with hip height; walking travel is removed so the page moves
the character and the feet do not slide). A round trip through the library is exact (tested in
`tests/test_cast3d.py`).

## Free forever: what code does on top of the moves

* **New office or route:** the page walks a character along points at its own walk's measured ground speed. A new
  room is new points and new reach targets; no generation.
* **Working at a desk:** `sit` plus two-bone arm IK to the keyboard, fingers tapping (`reachTo(..., typing)`).
  Pointing at a screen, reaching for a parcel, holding a tablet: the same IK to other points.
* **Paying attention:** the head turns toward whoever is talking (`lookAt`), within what a neck can do.
* **Nyx, Mote:** vertex ripple (tentacles), breath, bob and squash, all in code.
* **Mixing:** any loop under any one-shot (cheer while seated, nod while listening) by cross-fading.

## Adding a move later (8 credits, once, for every biped)

1. Find the action in Higgsfield's animation library (`animation_actions`, 678 actions).
2. Rig any biped once more with it: `generate_3d` model `meshy_rigging`, `model_url` = that character's Meshy mesh
   URL (below), `enable_animation: true`, `animation_action_id: <id>`. Cost: 8 credits.
3. Download the GLB into the raw folder, add an entry under `clips` in `art/cast3d/cast.json` (name, raw file,
   action id, loop, walk), then run `node art/cast3d/build_cast.mjs --raw <raw folder> --only clips`.
4. Every biped can now play it: `actor.play("<name>")`.

## The biped meshes to rig with (inputs for `meshy_rigging`)

| Who | Meshy mesh (unrigged) | Rig height |
|---|---|---|
| Pip | `https://d8j0ntlcm91z4.cloudfront.net/user_37raYK73mveR4zPEdz9xgOVsef4/hf_20261009_185818_339edf66-9b46-4987-b054-7cae91da5e71.glb` | 0.95 m |
| Jet | `https://d8j0ntlcm91z4.cloudfront.net/user_37raYK73mveR4zPEdz9xgOVsef4/hf_20261009_191440_77a22e57-0eba-4130-8046-31d3bb8dace8.glb` | 1.0 m |
| Voss | `https://d8j0ntlcm91z4.cloudfront.net/user_37raYK73mveR4zPEdz9xgOVsef4/hf_20261009_191435_6f7b86ee-ee48-4b76-a868-cc53c558851d.glb` | 1.0 m |
| Rook | `https://d8j0ntlcm91z4.cloudfront.net/user_37raYK73mveR4zPEdz9xgOVsef4/hf_20261009_191438_088174ba-07d8-4b57-a731-b43cda2b02b8.glb` | 1.8 m |

New moves are bought on Pip's mesh (the library's reference skeleton comes from Pip's idle rig).

## Adding a character later

A biped: Meshy multi-image (30 credits) from 2-4 clean views, then Meshy rigging (8 credits). Add it to
`characters` in `cast.json` (kind `biped`, its own walk), build it with `--only <id>`. All moves work at once.
Anything else (a creature, a machine): Tripo multiview (18 credits), kind `prop`/`octopus`/`blob`, motion in code.

## Rebuilding

```
cd art/cast3d && npm install          # @gltf-transform/cli 4.1.1 (meshoptimizer, sharp come with it)
node build_cast.mjs --raw <folder with the downloads>     # everything; or --only clips | cast | <id>
```

The raw downloads (15-66 MB each) are not committed; each source's job id and URL are in `cast.json`.

## Credits (Higgsfield, Plus plan; balance before the cast: 1,003.74)

| What | Model | Each | Count | Credits |
|---|---|---|---|---|
| Character turnarounds (7 sheets, 2k) | gpt_image_2_5 | 2.75 | 7 | 19.25 |
| Pip bake-off (Tripo, Meshy, Hunyuan) | 3D models | 18-30 | 3 | 71 |
| Prop reference sheets (12, 2k) | gpt_image_2_5 | 2.75 | 12 | 33 |
| Voss, Rook, Jet meshes | meshy_multi_image_to_3d | 30 | 3 | 90 |
| Nyx, Mote, cart meshes | tripo_h3_1_multiview_to_3d | 18 | 3 | 54 |
| Rigs with their own walks (Pip, Jet, Voss, Rook) | meshy_rigging | 8 | 4 | 32 |
| Move library (18 more moves on Pip's mesh) | meshy_rigging | 8 | 18 | 144 |
| **Total** | | | | **659.25** (balance after: 344.49) |
| Props (12 hero pieces) | tripo_h3_1_multiview_to_3d | 18 | 12 | 216 |

One rigging attempt on a sideways Tripo mesh failed and was refunded.
